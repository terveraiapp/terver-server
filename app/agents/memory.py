import os
import psycopg
from langchain_postgres import PostgresChatMessageHistory

TABLE_NAME = "amberlyn_chat_history"


def _get_db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise ValueError("DATABASE_URL environment variable is required")
    return url.replace("postgresql+psycopg://", "postgresql://")


def get_sync_connection() -> psycopg.Connection:
    return psycopg.connect(_get_db_url())


def ensure_tables_exist() -> None:
    with get_sync_connection() as conn:
        PostgresChatMessageHistory.create_tables(conn, TABLE_NAME)


def get_history(session_id: str) -> PostgresChatMessageHistory:
    conn = get_sync_connection()
    return PostgresChatMessageHistory(TABLE_NAME, session_id, sync_connection=conn)
