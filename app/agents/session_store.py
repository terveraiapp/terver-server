"""
Server-side store mapping session_id -> raw document text.
LRU-capped at 200 sessions to bound memory usage.
"""
import logging
import threading
from collections import OrderedDict

log = logging.getLogger(__name__)

_MAX_SESSIONS = 200
_store: OrderedDict[str, str] = OrderedDict()
_lock = threading.Lock()


def store_document_text(session_id: str, text: str) -> None:
    with _lock:
        if session_id in _store:
            _store.move_to_end(session_id)
            log.debug("Session store: updated existing session=%s (%d chars)", session_id, len(text))
        else:
            _store[session_id] = text
            log.debug("Session store: added session=%s (%d chars) — total sessions=%d", session_id, len(text), len(_store))
        while len(_store) > _MAX_SESSIONS:
            evicted, _ = _store.popitem(last=False)
            log.info("Session store: evicted oldest session=%s (LRU cap=%d)", evicted, _MAX_SESSIONS)
        _store[session_id] = text


def get_document_text(session_id: str) -> str:
    with _lock:
        text = _store.get(session_id, "")
        log.debug(
            "Session store: get session=%s found=%s len=%d",
            session_id, bool(text), len(text),
        )
        return text
