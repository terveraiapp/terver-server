import asyncio
import json
import logging
import os
import threading
import time
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, AIMessage

from app.models.schemas import ChatRequest
from app.providers import get_llm
from app.agents.amberlyn import build_amberlyn_graph, load_state_from_history, persist_message
from app.agents.session_store import get_document_text

log = logging.getLogger(__name__)
router = APIRouter()

_graph_cache: dict = {}
_graph_lock = threading.Lock()


def _get_graph() -> object:
    provider = os.environ.get("ACTIVE_PROVIDER", "gemini")
    if provider not in _graph_cache:
        with _graph_lock:
            if provider not in _graph_cache:
                log.info("Building Amberlyn graph for provider=%s", provider)
                _graph_cache[provider] = build_amberlyn_graph(get_llm())
                log.info("Amberlyn graph built and cached for provider=%s", provider)
    return _graph_cache[provider]


@router.post("/chat/{session_id}")
async def chat_with_amberlyn(session_id: str, request: ChatRequest):
    log.info("=== /chat START session=%s message_len=%d ===", session_id, len(request.message))
    log.debug("Chat message: %r", request.message[:200])
    t0 = time.perf_counter()

    graph = _get_graph()

    raw_text = get_document_text(session_id)
    log.info(
        "Session store lookup: session=%s raw_text_available=%s len=%d",
        session_id, bool(raw_text), len(raw_text),
    )

    log.debug("Loading chat history from DB for session=%s", session_id)
    t_db = time.perf_counter()
    state = await asyncio.to_thread(
        load_state_from_history,
        session_id,
        request.document_context,
        raw_text,
    )
    db_ms = (time.perf_counter() - t_db) * 1000
    log.info(
        "History loaded: session=%s existing_messages=%d db_ms=%.0f",
        session_id, len(state["messages"]), db_ms,
    )

    user_message = HumanMessage(content=request.message)
    state["messages"] = list(state["messages"]) + [user_message]

    log.debug("Persisting user message for session=%s", session_id)
    await asyncio.to_thread(persist_message, session_id, user_message)

    async def event_stream():
        log.info("Chat SSE stream opened — session=%s", session_id)
        full_response = ""
        token_count = 0
        llm_start = time.perf_counter()

        try:
            log.info(
                "Invoking Amberlyn graph: session=%s total_messages=%d",
                session_id, len(state["messages"]),
            )
            async for event in graph.astream(state, stream_mode="messages"):
                msg = event[0] if isinstance(event, tuple) else event
                content = msg.content if hasattr(msg, "content") else ""
                if isinstance(content, str) and content:
                    full_response += content
                    token_count += 1
                    if token_count % 10 == 0:
                        log.debug(
                            "Chat streaming: %d chunks, %d chars — session=%s",
                            token_count, len(full_response), session_id,
                        )
                    yield f"data: {json.dumps({'type': 'token', 'token': content})}\n\n"

            llm_elapsed = (time.perf_counter() - llm_start) * 1000
            total_elapsed = (time.perf_counter() - t0) * 1000
            log.info(
                "Chat done: session=%s tokens=%d response_chars=%d llm_ms=%.0f total_ms=%.0f",
                session_id, token_count, len(full_response), llm_elapsed, total_elapsed,
            )

            await asyncio.to_thread(persist_message, session_id, AIMessage(content=full_response))
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            log.error("Chat error after %.0fms — session=%s: %s", elapsed, session_id, e, exc_info=True)
            msg_str = str(e)
            if "429" in msg_str or "quota" in msg_str.lower() or "rate" in msg_str.lower():
                clean = "API quota exceeded. Please wait a moment and try again."
            else:
                clean = "Something went wrong. Please try again."
            yield f"data: {json.dumps({'type': 'error', 'message': clean})}\n\n"

        log.info("=== /chat END session=%s ===", session_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
