import logging
import time
from typing import Annotated
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage
from langchain_core.language_models import BaseChatModel
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from app.agents.prompts import AMBERLYN_SYSTEM_PROMPT
from app.agents.memory import get_messages, add_message

log = logging.getLogger(__name__)


class AmberlynState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    document_context: str
    raw_document_text: str
    session_id: str
    summary: str


def build_amberlyn_graph(llm: BaseChatModel):
    log.info("Building Amberlyn LangGraph state machine")

    def summarize_node(state: AmberlynState) -> dict:
        msg_count = len(state["messages"])
        session_id = state.get("session_id", "?")
        log.debug("summarize_node: session=%s message_count=%d", session_id, msg_count)

        if msg_count <= 12:
            log.debug("summarize_node: skipping (<=12 messages)")
            return {}

        log.info("summarize_node: summarising %d older messages for session=%s", msg_count - 6, session_id)
        t0 = time.perf_counter()
        oldest = state["messages"][:-6]
        recent = state["messages"][-6:]
        existing_summary = state.get("summary", "")
        prompt = (
            f"Previous summary:\n{existing_summary}\n\n"
            f"New conversation turns to summarise:\n"
            + "\n".join(f"{m.type}: {m.content}" for m in oldest)
            + "\n\nWrite a concise updated summary that captures all important facts discussed."
        )
        new_summary = llm.invoke([HumanMessage(content=prompt)]).content
        elapsed = (time.perf_counter() - t0) * 1000
        log.info("summarize_node: done in %.0fms, summary_len=%d — session=%s", elapsed, len(new_summary), session_id)
        return {"summary": new_summary, "messages": recent}

    def chat_node(state: AmberlynState) -> dict:
        session_id = state.get("session_id", "?")
        msg_count = len(state["messages"])
        raw_text_len = len(state.get("raw_document_text", "") or "")
        doc_ctx_len = len(state.get("document_context", "") or "")
        log.info(
            "chat_node: session=%s messages=%d doc_context_len=%d raw_text_len=%d",
            session_id, msg_count, doc_ctx_len, raw_text_len,
        )

        system_content = AMBERLYN_SYSTEM_PROMPT.format(
            document_context=state.get("document_context", "No document analysed yet."),
            raw_document_text=state.get("raw_document_text", "") or "Not available for this document type.",
            summary=state.get("summary", "No previous conversation."),
        )
        log.debug("chat_node: system prompt length=%d chars — session=%s", len(system_content), session_id)

        t0 = time.perf_counter()
        response = llm.invoke([SystemMessage(content=system_content)] + state["messages"])
        elapsed = (time.perf_counter() - t0) * 1000
        log.info(
            "chat_node: LLM responded in %.0fms, response_len=%d — session=%s",
            elapsed, len(response.content), session_id,
        )
        return {"messages": [response]}

    graph = StateGraph(AmberlynState)
    graph.add_node("summarize", summarize_node)
    graph.add_node("chat", chat_node)
    graph.set_entry_point("summarize")
    graph.add_edge("summarize", "chat")
    graph.add_edge("chat", END)
    compiled = graph.compile()
    log.info("Amberlyn graph compiled successfully")
    return compiled


def load_state_from_history(session_id: str, document_context: str, raw_document_text: str = "") -> AmberlynState:
    log.debug("load_state_from_history: session=%s", session_id)
    messages = get_messages(session_id)
    log.debug("load_state_from_history: loaded %d messages for session=%s", len(messages), session_id)
    return AmberlynState(
        messages=messages,
        document_context=document_context,
        raw_document_text=raw_document_text,
        session_id=session_id,
        summary="",
    )


def persist_message(session_id: str, message: BaseMessage) -> None:
    log.debug("persist_message: type=%s session=%s", message.type, session_id)
    add_message(session_id, message)
