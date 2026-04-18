import asyncio
import json
import os
import threading
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, AIMessage

from app.models.schemas import ChatRequest
from app.providers import get_llm
from app.agents.amberlyn import build_amberlyn_graph, load_state_from_history, persist_message
from app.agents.session_store import get_document_text

router = APIRouter()
_graph_cache: dict = {}
_graph_lock = threading.Lock()


def _get_graph() -> object:
    provider = os.environ.get("ACTIVE_PROVIDER", "gemini")
    if provider not in _graph_cache:
        with _graph_lock:
            if provider not in _graph_cache:  # double-checked locking
                _graph_cache[provider] = build_amberlyn_graph(get_llm())
    return _graph_cache[provider]


@router.post("/chat/{session_id}")
async def chat_with_amberlyn(session_id: str, request: ChatRequest):
    graph = _get_graph()

    raw_text = get_document_text(session_id)
    state = await asyncio.to_thread(
        load_state_from_history,
        session_id,
        request.document_context,
        raw_text,
    )
    user_message = HumanMessage(content=request.message)
    state["messages"] = list(state["messages"]) + [user_message]
    await asyncio.to_thread(persist_message, session_id, user_message)

    async def event_stream():
        full_response = ""
        try:
            async for event in graph.astream(state, stream_mode="messages"):
                msg = event[0] if isinstance(event, tuple) else event
                content = msg.content if hasattr(msg, "content") else ""
                if isinstance(content, str) and content:
                    full_response += content
                    yield f"data: {json.dumps({'type': 'token', 'token': content})}\n\n"
            await asyncio.to_thread(persist_message, session_id, AIMessage(content=full_response))
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            msg = str(e)
            if "429" in msg or "quota" in msg.lower() or "rate" in msg.lower():
                clean = "API quota exceeded. Please wait a moment and try again."
            else:
                clean = "Something went wrong. Please try again."
            yield f"data: {json.dumps({'type': 'error', 'message': clean})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
