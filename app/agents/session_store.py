"""
Server-side store mapping session_id → raw document text.
Used to give Amberlyn full document content so she can quote exact lines.
LRU-capped at 200 sessions to bound memory usage.
"""
import threading
from collections import OrderedDict

_MAX_SESSIONS = 200
_store: OrderedDict[str, str] = OrderedDict()
_lock = threading.Lock()


def store_document_text(session_id: str, text: str) -> None:
    with _lock:
        if session_id in _store:
            _store.move_to_end(session_id)
        _store[session_id] = text
        while len(_store) > _MAX_SESSIONS:
            _store.popitem(last=False)


def get_document_text(session_id: str) -> str:
    with _lock:
        return _store.get(session_id, "")
