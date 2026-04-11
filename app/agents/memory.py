import os
import psycopg
from langchain_postgres import PostgresChatMessageHistory
from langchain_core.messages import BaseMessage

TABLE_NAME = "amberlyn_chat_history"


def _get_db_url() -> str | None:
    url = os.environ.get("DATABASE_URL", "")
    if not url or "ep-xxx" in url or "password" in url:
        return None
    return url.replace("postgresql+psycopg://", "postgresql://")


def ensure_tables_exist() -> None:
    url = _get_db_url()
    if not url:
        raise ValueError("DATABASE_URL not configured")
    with psycopg.connect(url) as conn:
        PostgresChatMessageHistory.create_tables(conn, TABLE_NAME)


def get_messages(session_id: str) -> list[BaseMessage]:
    """Load all messages for a session. Returns empty list if DB unavailable."""
    url = _get_db_url()
    if not url:
        return []
    try:
        with psycopg.connect(url) as conn:
            history = PostgresChatMessageHistory(TABLE_NAME, session_id, sync_connection=conn)
            return list(history.messages)
    except Exception:
        return []


def add_message(session_id: str, message: BaseMessage) -> None:
    """Persist a single message. No-op if DB unavailable."""
    url = _get_db_url()
    if not url:
        return
    try:
        with psycopg.connect(url) as conn:
            history = PostgresChatMessageHistory(TABLE_NAME, session_id, sync_connection=conn)
            history.add_message(message)
    except Exception:
        pass
