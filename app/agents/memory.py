import logging
import os
import psycopg
from langchain_postgres import PostgresChatMessageHistory
from langchain_core.messages import BaseMessage

log = logging.getLogger(__name__)

TABLE_NAME = "amberlyn_chat_history"


def _get_db_url() -> str | None:
    url = os.environ.get("DATABASE_URL", "")
    if not url or "ep-xxx" in url or url.endswith("password@"):
        log.debug("DATABASE_URL not configured or is placeholder — DB disabled")
        return None
    return url.replace("postgresql+psycopg://", "postgresql://")


def ensure_tables_exist() -> None:
    url = _get_db_url()
    if not url:
        raise ValueError("DATABASE_URL not configured")
    log.info("Creating/verifying chat history table: %s", TABLE_NAME)
    with psycopg.connect(url) as conn:
        PostgresChatMessageHistory.create_tables(conn, TABLE_NAME)
    log.info("Chat history table ready")


def get_messages(session_id: str) -> list[BaseMessage]:
    url = _get_db_url()
    if not url:
        log.debug("get_messages: DB unavailable, returning empty list for session=%s", session_id)
        return []
    try:
        log.debug("get_messages: querying DB for session=%s", session_id)
        with psycopg.connect(url) as conn:
            history = PostgresChatMessageHistory(TABLE_NAME, session_id, sync_connection=conn)
            messages = list(history.messages)
        log.debug("get_messages: found %d messages for session=%s", len(messages), session_id)
        return messages
    except Exception as e:
        log.error("get_messages failed for session=%s: %s", session_id, e, exc_info=True)
        return []


def add_message(session_id: str, message: BaseMessage) -> None:
    url = _get_db_url()
    if not url:
        log.debug("add_message: DB unavailable, skipping persist for session=%s", session_id)
        return
    try:
        log.debug("add_message: persisting %s message for session=%s", message.type, session_id)
        with psycopg.connect(url) as conn:
            history = PostgresChatMessageHistory(TABLE_NAME, session_id, sync_connection=conn)
            history.add_message(message)
        log.debug("add_message: persisted successfully for session=%s", session_id)
    except Exception as e:
        log.error("add_message failed for session=%s: %s", session_id, e, exc_info=True)
