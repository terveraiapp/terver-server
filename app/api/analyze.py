import json
import logging
import os
import re
import time
import uuid
from fastapi import APIRouter, UploadFile, File
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage

from app.services.document import process_upload
from app.providers import get_llm
from app.agents.prompts import ANALYSIS_SYSTEM_PROMPT
from app.agents.session_store import store_document_text


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

log = logging.getLogger(__name__)
router = APIRouter()


def _build_content_blocks(mime_type: str, payload: str) -> list[dict]:
    if mime_type == "text/plain":
        log.debug("Building text content blocks (DOCX path), text length=%d", len(payload))
        return [
            {"type": "text", "text": f"Document contents (extracted from Word file):\n\n{payload}"},
            {"type": "text", "text": (
                "Analyse this property document and return the JSON risk assessment as instructed.\n\n"
                "This document was submitted as a Word file, so pixel-level layout and ink-signature inspection "
                "are not available. You MUST still perform a FULL and RIGOROUS assessment using the text alone. "
                "Specifically:\n"
                "- Ownership Integrity: trace every named party, date, and transaction reference. Flag any gap, "
                "contradiction, or missing link in the chain of title.\n"
                "- Document Completeness: identify every field that is present, ambiguous, or absent. A missing "
                "signature clause in the text is still a FAIL — note it explicitly.\n"
                "- Registration Status: look for deed/registry numbers, stamp duty mentions, Land Commission "
                "references. Absence of any of these is a red flag.\n"
                "- Boundary & Survey: extract and cross-check all plot numbers, survey references, acreage figures, "
                "and boundary descriptions. Inconsistencies or vague descriptions must be flagged.\n"
                "- Fraud Indicators: look for internal contradictions in dates or parties, copy-paste artefacts, "
                "unusually vague language, missing consideration amounts, or clauses that override standard protections.\n\n"
                "Do not soften findings because the source is a Word document. Apply exactly the same rigour "
                "as you would to a scanned deed. Return ONLY valid JSON."
            )},
        ]

    provider = os.environ.get("ACTIVE_PROVIDER", "gemini").lower()
    log.debug("Building binary content blocks: provider=%s mime=%s payload_len=%d", provider, mime_type, len(payload))

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

    return [
        file_block,
        {"type": "text", "text": "Analyse this property document and return the JSON risk assessment as instructed."},
    ]


@router.post("/analyze")
async def analyze_document(file: UploadFile = File(...)):
    session_id = str(uuid.uuid4())
    log.info("=== /analyze START session=%s filename=%r ===", session_id, file.filename)
    t0 = time.perf_counter()

    payload, mime_type, raw_text = await process_upload(file)
    filename = file.filename or "document"

    doc_label = f"=== {filename} ===\n\n"
    store_document_text(session_id, doc_label + (raw_text or "(Visual document — no text layer extracted)"))
    log.info("Session store: saved %d chars of raw text for session=%s", len(raw_text), session_id)

    llm = get_llm()
    content_blocks = _build_content_blocks(mime_type, payload)
    log.info("LLM content blocks: %d blocks for session=%s", len(content_blocks), session_id)

    messages = [
        SystemMessage(content=ANALYSIS_SYSTEM_PROMPT),
        HumanMessage(content=content_blocks),
    ]

    async def event_stream():
        log.info("SSE stream opened for session=%s", session_id)
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id, 'document_name': filename})}\n\n"

        full_response = ""
        token_count = 0
        llm_start = time.perf_counter()
        log.info("Sending to LLM (provider=%s model=%s) session=%s",
                 os.environ.get("ACTIVE_PROVIDER", "gemini"),
                 getattr(llm, "model", "unknown"),
                 session_id)
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
                        log.debug("Streaming tokens: %d chunks, %d chars so far — session=%s",
                                  token_count, len(full_response), session_id)
                    yield f"data: {json.dumps({'type': 'token', 'token': token})}\n\n"

            llm_elapsed = (time.perf_counter() - llm_start) * 1000
            total_elapsed = (time.perf_counter() - t0) * 1000
            log.info(
                "LLM done: session=%s tokens=%d response_chars=%d llm_ms=%.0f total_ms=%.0f",
                session_id, token_count, len(full_response), llm_elapsed, total_elapsed,
            )
            clean = _extract_json(full_response)
            if clean != full_response:
                log.info("JSON extracted from LLM wrapper (original %d chars -> %d chars) — session=%s",
                         len(full_response), len(clean), session_id)
            yield f"data: {json.dumps({'type': 'done', 'raw': clean})}\n\n"

        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            log.error("LLM error after %.0fms — session=%s: %s", elapsed, session_id, e, exc_info=True)
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                clean = "API quota exceeded. Please wait a moment and try again."
            elif "401" in msg or "API_KEY" in msg:
                clean = "Invalid API key. Please check your GEMINI_API_KEY."
            elif "404" in msg or "NOT_FOUND" in msg:
                clean = "Analysis failed. Please try again."
            else:
                clean = "Analysis failed. Please try again."
            yield f"data: {json.dumps({'type': 'error', 'message': clean})}\n\n"

        log.info("=== /analyze END session=%s ===", session_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Session-Id": session_id},
    )
