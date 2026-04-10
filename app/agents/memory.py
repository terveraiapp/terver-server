import os
import psycopg
from langchain_postgres import PostgresChatMessageHistory
from langchain_core.messages import BaseMessage

TABLE_NAME = "amberlyn_chat_history"


def _get_db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise ValueError("DATABASE_URL environment variable is required")
    return url.replace("postgresql+psycopg://", "postgresql://")


def ensure_tables_exist() -> None:
    with psycopg.connect(_get_db_url()) as conn:
        PostgresChatMessageHistory.create_tables(conn, TABLE_NAME)


def get_messages(session_id: str) -> list[BaseMessage]:
    """Load all messages for a session, closing the connection immediately after."""
    with psycopg.connect(_get_db_url()) as conn:
        history = PostgresChatMessageHistory(TABLE_NAME, session_id, sync_connection=conn)
        return list(history.messages)


def add_message(session_id: str, message: BaseMessage) -> None:
    """Persist a single message, closing the connection immediately after."""
    with psycopg.connect(_get_db_url()) as conn:
        history = PostgresChatMessageHistory(TABLE_NAME, session_id, sync_connection=conn)
        history.add_message(message)
