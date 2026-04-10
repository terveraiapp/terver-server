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

    state = await asyncio.to_thread(
        load_state_from_history,
        session_id,
        request.document_context,
    )
    user_message = HumanMessage(content=request.message)
    state["messages"] = list(state["messages"]) + [user_message]
    await asyncio.to_thread(persist_message, session_id, user_message)

    async def event_stream():
        full_response = ""
        try:
            async for event in graph.astream(state, stream_mode="messages"):
                if isinstance(event, tuple):
                    _, payload = event
                    if hasattr(payload, "content") and payload.content:
                        full_response += payload.content
                        yield f"data: {json.dumps({'type': 'token', 'token': payload.content})}\n\n"
                elif hasattr(event, "content") and event.content:
                    full_response += event.content
                    yield f"data: {json.dumps({'type': 'token', 'token': event.content})}\n\n"
            await asyncio.to_thread(persist_message, session_id, AIMessage(content=full_response))
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
