import json
import uuid
from fastapi import APIRouter, UploadFile, File
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage

from app.services.document import process_upload
from app.providers import get_llm
from app.agents.prompts import ANALYSIS_SYSTEM_PROMPT

router = APIRouter()


@router.post("/analyze")
async def analyze_document(file: UploadFile = File(...)):
    session_id = str(uuid.uuid4())
    b64_content, mime_type = await process_upload(file)
    filename = file.filename or "document"

    llm = get_llm()

    if mime_type == "application/pdf":
        content_block = {
            "type": "document",
            "source": {"type": "base64", "media_type": mime_type, "data": b64_content},
        }
    else:
        content_block = {
            "type": "image_url",
            "image_url": {"url": f"data:{mime_type};base64,{b64_content}"},
        }

    messages = [
        SystemMessage(content=ANALYSIS_SYSTEM_PROMPT),
        HumanMessage(content=[
            content_block,
            {"type": "text", "text": "Analyse this property document and return the JSON risk assessment as instructed."},
        ]),
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
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Session-Id": session_id},
    )
