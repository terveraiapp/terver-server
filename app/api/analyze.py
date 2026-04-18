import json
import os
import uuid
from fastapi import APIRouter, UploadFile, File
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage

from app.services.document import process_upload
from app.providers import get_llm
from app.agents.prompts import ANALYSIS_SYSTEM_PROMPT

router = APIRouter()


def _build_content_blocks(mime_type: str, payload: str) -> list[dict]:
    """Return the list of content blocks for the HumanMessage."""
    # Word docs come back as extracted plain text
    if mime_type == "text/plain":
        return [
            {"type": "text", "text": f"Document contents (extracted from Word file):\n\n{payload}"},
            {"type": "text", "text": "Analyse this property document and return the JSON risk assessment as instructed. Note: this is a Word document so layout/signature analysis is not possible — focus on the textual content."},
        ]

    provider = os.environ.get("ACTIVE_PROVIDER", "gemini").lower()
    # Claude uses Anthropic's document block for PDFs
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
    payload, mime_type = await process_upload(file)
    filename = file.filename or "document"

    llm = get_llm()
    content_blocks = _build_content_blocks(mime_type, payload)

    messages = [
        SystemMessage(content=ANALYSIS_SYSTEM_PROMPT),
        HumanMessage(content=content_blocks),
    ]

    async def event_stream():
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id, 'document_name': filename})}\n\n"
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
            elif "404" in msg or "NOT_FOUND" in msg:
                clean = "Analysis failed. Please try again."
            else:
                clean = "Analysis failed. Please try again."
            yield f"data: {json.dumps({'type': 'error', 'message': clean})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Session-Id": session_id},
    )
