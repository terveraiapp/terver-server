import json
import logging
import os
import re
import time
import uuid
from typing import List
from fastapi import APIRouter, UploadFile, File
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage

from app.services.document import process_upload
from app.providers import get_llm
from app.agents.prompts import CASE_ANALYSIS_SYSTEM_PROMPT
from app.agents.session_store import store_document_text

log = logging.getLogger(__name__)
router = APIRouter()


def _extract_json(text: str) -> str:
    """Strip markdown fences and isolate the JSON object from LLM output."""
    text = text.strip()
    fenced = re.match(r'^```(?:json)?\s*([\s\S]*?)\s*```$', text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    start, end = text.find('{'), text.rfind('}')
    if start != -1 and end != -1:
        return text[start:end + 1]
    return text


def _file_content_blocks(filename: str, mime_type: str, payload: str) -> list[dict]:
    label = {"type": "text", "text": f"--- Document: {filename} ---"}

    if mime_type == "text/plain":
        log.debug("Content block for %r: text/plain %d chars", filename, len(payload))
        return [
            label,
            {"type": "text", "text": f"(Word document — extracted text)\n\n{payload}"},
        ]

    provider = os.environ.get("ACTIVE_PROVIDER", "gemini").lower()
    log.debug("Content block for %r: binary mime=%s provider=%s", filename, mime_type, provider)

    if provider == "claude" and mime_type == "application/pdf":
        file_block: dict = {
            "type": "document",
            "source": {"type": "base64", "media_type": mime_type, "data": payload},
        }
    else:
        file_block = {
            "type": "image_url",
            "image_url": {"url": f"data:{mime_type};base64,{payload}"},
        }

    return [label, file_block]


@router.post("/analyze-case")
async def analyze_case(files: List[UploadFile] = File(...)):
    session_id = str(uuid.uuid4())
    log.info("=== /analyze-case START session=%s file_count=%d ===", session_id, len(files))
    t0 = time.perf_counter()

    if len(files) < 2:
        from fastapi import HTTPException
        log.warning("analyze-case called with only %d file(s) — rejecting", len(files))
        raise HTTPException(status_code=400, detail="Case analysis requires at least 2 documents.")

    for f in files:
        log.info("  File queued: %r content_type=%r", f.filename, f.content_type)

    # Process all uploads first so we can fail fast before streaming
    processed: list[tuple[str, str, str, str]] = []  # (filename, payload, mime_type, raw_text)
    for i, file in enumerate(files):
        log.info("Processing file %d/%d: %r", i + 1, len(files), file.filename)
        t_file = time.perf_counter()
        payload, mime_type, raw_text = await process_upload(file)
        file_ms = (time.perf_counter() - t_file) * 1000
        log.info(
            "File %d/%d done: %r mime=%s payload_len=%d raw_text_len=%d (%.0fms)",
            i + 1, len(files), file.filename, mime_type, len(payload), len(raw_text), file_ms,
        )
        processed.append((file.filename or f"document_{i+1}", payload, mime_type, raw_text))

    upload_ms = (time.perf_counter() - t0) * 1000
    log.info("All %d files processed in %.0fms — session=%s", len(processed), upload_ms, session_id)

    # Store concatenated raw text for Amberlyn chat grounding
    text_sections = []
    for fname, _, _, raw_text in processed:
        text_sections.append(
            f"=== {fname} ===\n\n{raw_text or '(Visual document — no text layer extracted)'}"
        )
    combined_text = "\n\n".join(text_sections)
    store_document_text(session_id, combined_text)
    log.info("Session store: saved %d chars of combined raw text — session=%s", len(combined_text), session_id)

    # Build one HumanMessage with all documents as content blocks
    content_blocks: list[dict] = []
    for filename, payload, mime_type, _ in processed:
        blocks = _file_content_blocks(filename, mime_type, payload)
        content_blocks.extend(blocks)
        log.debug("Added %d content blocks for %r (total so far: %d)", len(blocks), filename, len(content_blocks))

    content_blocks.append({
        "type": "text",
        "text": (
            f"The {len(processed)} documents above all relate to the same property case. "
            "Cross-reference all of them and return the unified JSON case risk assessment as instructed."
        ),
    })

    log.info(
        "Total content blocks: %d across %d documents — session=%s",
        len(content_blocks), len(processed), session_id,
    )

    llm = get_llm()
    filenames = [fname for fname, _, _, _ in processed]
    case_name = f"Case — {len(filenames)} documents"

    messages = [
        SystemMessage(content=CASE_ANALYSIS_SYSTEM_PROMPT),
        HumanMessage(content=content_blocks),
    ]

    async def event_stream():
        log.info("SSE stream opened for case session=%s", session_id)
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id, 'document_name': case_name, 'is_case': True, 'file_count': len(filenames)})}\n\n"

        full_response = ""
        token_count = 0
        llm_start = time.perf_counter()
        log.info(
            "Sending case to LLM: provider=%s model=%s files=%s session=%s",
            os.environ.get("ACTIVE_PROVIDER", "gemini"),
            getattr(llm, "model", "unknown"),
            filenames,
            session_id,
        )

        try:
            async for chunk in llm.astream(messages):
                raw = chunk.content if hasattr(chunk, "content") else chunk
                token = raw if isinstance(raw, str) else (
                    raw[0].get("text", "") if isinstance(raw, list) and raw else ""
                )
                if token:
                    full_response += token
                    token_count += 1
                    if token_count % 20 == 0:
                        log.debug(
                            "Case streaming: %d chunks, %d chars so far — session=%s",
                            token_count, len(full_response), session_id,
                        )
                    yield f"data: {json.dumps({'type': 'token', 'token': token})}\n\n"

            llm_elapsed = (time.perf_counter() - llm_start) * 1000
            total_elapsed = (time.perf_counter() - t0) * 1000
            log.info(
                "Case LLM done: session=%s tokens=%d response_chars=%d llm_ms=%.0f total_ms=%.0f",
                session_id, token_count, len(full_response), llm_elapsed, total_elapsed,
            )
            clean = _extract_json(full_response)
            if clean != full_response:
                log.info("JSON extracted from LLM wrapper (original %d chars -> %d chars) — session=%s",
                         len(full_response), len(clean), session_id)
            yield f"data: {json.dumps({'type': 'done', 'raw': clean})}\n\n"

        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            log.error("Case LLM error after %.0fms — session=%s: %s", elapsed, session_id, e, exc_info=True)
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                clean = "API quota exceeded. Please wait a moment and try again."
            elif "401" in msg or "API_KEY" in msg:
                clean = "Invalid API key. Please check your GEMINI_API_KEY."
            else:
                clean = "Case analysis failed. Please try again."
            yield f"data: {json.dumps({'type': 'error', 'message': clean})}\n\n"

        log.info("=== /analyze-case END session=%s ===", session_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Session-Id": session_id},
    )
