import json
import os
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, AIMessage

from app.models.schemas import ChatRequest
from app.providers import get_llm
from app.agents.amberlyn import build_amberlyn_graph, load_state_from_history, persist_message

router = APIRouter()
_graph_cache: dict = {}


def _get_graph():
    provider_key = os.environ.get("ACTIVE_PROVIDER", "gemini")
    if provider_key not in _graph_cache:
        _graph_cache[provider_key] = build_amberlyn_graph(get_llm())
    return _graph_cache[provider_key]


@router.post("/chat/{session_id}")
async def chat_with_amberlyn(session_id: str, request: ChatRequest):
    graph = _get_graph()

    state = load_state_from_history(
        session_id=session_id,
        document_context=request.document_context,
    )
    user_message = HumanMessage(content=request.message)
    state["messages"] = list(state["messages"]) + [user_message]
    persist_message(session_id, user_message)

    async def event_stream():
        full_response = ""
        async for event in graph.astream(state, stream_mode="messages"):
            if isinstance(event, tuple):
                _, payload = event
                if hasattr(payload, "content") and payload.content:
                    full_response += payload.content
                    yield f"data: {json.dumps({'type': 'token', 'token': payload.content})}\n\n"
            elif hasattr(event, "content") and event.content:
                full_response += event.content
                yield f"data: {json.dumps({'type': 'token', 'token': event.content})}\n\n"

        persist_message(session_id, AIMessage(content=full_response))
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
