"""
Centralised logging configuration.
Call setup_logging() once at startup (main.py lifespan).
All modules import `log = logging.getLogger(__name__)` and use it directly.
Render captures stdout, so we stream there.
"""
import logging
import sys


def setup_logging() -> None:
    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(fmt)
    handler.setLevel(logging.DEBUG)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Avoid duplicate handlers if called more than once
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        root.addHandler(handler)

    # Quieten noisy third-party loggers
    for noisy in ("httpcore", "httpx", "urllib3", "hpack", "h2", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
