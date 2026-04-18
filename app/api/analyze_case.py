import json
import os
import uuid
from typing import List
from fastapi import APIRouter, UploadFile, File
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage

from app.services.document import process_upload
from app.providers import get_llm
from app.agents.prompts import CASE_ANALYSIS_SYSTEM_PROMPT
from app.agents.session_store import store_document_text

router = APIRouter()


def _file_content_blocks(filename: str, mime_type: str, payload: str) -> list[dict]:
    """Build content blocks for one file within a multi-doc case."""
    label = {"type": "text", "text": f"--- Document: {filename} ---"}

    if mime_type == "text/plain":
        return [
            label,
            {"type": "text", "text": f"(Word document — extracted text)\n\n{payload}"},
        ]

    provider = os.environ.get("ACTIVE_PROVIDER", "gemini").lower()
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
    if len(files) < 2:
        # Fallback: single file should use /analyze
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Case analysis requires at least 2 documents.")

    session_id = str(uuid.uuid4())
    filenames = [f.filename or f"document_{i+1}" for i, f in enumerate(files)]

    # Process all uploads first so we can fail fast before streaming
    processed: list[tuple[str, str, str, str]] = []  # (filename, payload, mime_type, raw_text)
    for file in files:
        payload, mime_type, raw_text = await process_upload(file)
        processed.append((file.filename or "document", payload, mime_type, raw_text))

    llm = get_llm()

    # Store concatenated raw text for all docs so Amberlyn can quote exact lines in chat
    text_sections = []
    for fname, _, _, raw_text in processed:
        text_sections.append(f"=== {fname} ===\n\n{raw_text or '(Visual document — no text layer extracted)'}")
    store_document_text(session_id, "\n\n".join(text_sections))

    # Build one big HumanMessage with all documents as content blocks
    content_blocks: list[dict] = []
    for filename, payload, mime_type, _ in processed:
        content_blocks.extend(_file_content_blocks(filename, mime_type, payload))

    content_blocks.append({
        "type": "text",
        "text": (
            f"The {len(processed)} documents above all relate to the same property case. "
            "Cross-reference all of them and return the unified JSON case risk assessment as instructed."
        ),
    })

    messages = [
        SystemMessage(content=CASE_ANALYSIS_SYSTEM_PROMPT),
        HumanMessage(content=content_blocks),
    ]

    case_name = f"Case — {len(filenames)} documents"

    async def event_stream():
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id, 'document_name': case_name, 'is_case': True, 'file_count': len(filenames)})}\n\n"
        full_response = ""
        try:
            async for chunk in llm.astream(messages):
                raw = chunk.content if hasattr(chunk, "content") else chunk
                token = raw if isinstance(raw, str) else (raw[0].get("text", "") if isinstance(raw, list) and raw else "")
                if token:
                    full_response += token
                    yield f"data: {json.dumps({'type': 'token', 'token': token})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'raw': full_response})}\n\n"
        except Exception as e:
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                clean = "API quota exceeded. Please wait a moment and try again."
            elif "401" in msg or "API_KEY" in msg:
                clean = "Invalid API key. Please check your GEMINI_API_KEY."
            else:
                clean = "Case analysis failed. Please try again."
            yield f"data: {json.dumps({'type': 'error', 'message': clean})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Session-Id": session_id},
    )
