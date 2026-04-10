from typing import Annotated
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage
from langchain_core.language_models import BaseChatModel
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from app.agents.prompts import AMBERLYN_SYSTEM_PROMPT
from app.agents.memory import get_messages, add_message


class AmberlynState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    document_context: str
    session_id: str
    summary: str


def build_amberlyn_graph(llm: BaseChatModel):
    def summarize_node(state: AmberlynState) -> dict:
        if len(state["messages"]) <= 12:
            return {}
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
        return {"summary": new_summary, "messages": recent}

    def chat_node(state: AmberlynState) -> dict:
        system_content = AMBERLYN_SYSTEM_PROMPT.format(
            document_context=state.get("document_context", "No document analysed yet."),
            summary=state.get("summary", "No previous conversation."),
        )
        response = llm.invoke([SystemMessage(content=system_content)] + state["messages"])
        return {"messages": [response]}

    graph = StateGraph(AmberlynState)
    graph.add_node("summarize", summarize_node)
    graph.add_node("chat", chat_node)
    graph.set_entry_point("summarize")
    graph.add_edge("summarize", "chat")
    graph.add_edge("chat", END)
    return graph.compile()


def load_state_from_history(session_id: str, document_context: str) -> AmberlynState:
    messages = get_messages(session_id)
    return AmberlynState(
        messages=messages,
        document_context=document_context,
        session_id=session_id,
        summary="",
    )


def persist_message(session_id: str, message: BaseMessage) -> None:
    add_message(session_id, message)
