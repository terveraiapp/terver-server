import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from app.core.logging_config import setup_logging
setup_logging()

log = logging.getLogger(__name__)

from app.api.analyze import router as analyze_router
from app.api.analyze_case import router as analyze_case_router
from app.api.chat import router as chat_router
from app.agents.memory import ensure_tables_exist

PING_INTERVAL = 290


async def _self_ping():
    try:
        import httpx
        url = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:8000") + "/health"
        async with httpx.AsyncClient(timeout=10) as client:
            while True:
                await asyncio.sleep(PING_INTERVAL)
                try:
                    await client.get(url)
                    log.debug("Self-ping OK -> %s", url)
                except Exception as e:
                    log.warning("Self-ping failed: %s", e)
    except ImportError:
        log.warning("httpx not available — self-ping disabled")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("=== Terver API starting up ===")
    log.info("ACTIVE_PROVIDER=%s", os.environ.get("ACTIVE_PROVIDER", "gemini"))
    log.info("CORS_ORIGINS=%s", os.environ.get("CORS_ORIGINS", "http://localhost:3000"))
    log.info("DATABASE_URL configured=%s", bool(os.environ.get("DATABASE_URL")))

    try:
        ensure_tables_exist()
        log.info("Database tables ready")
    except Exception as e:
        log.warning("DB init failed (%s) — chat persistence disabled", e)

    task = asyncio.create_task(_self_ping())
    log.info("Self-ping task started (interval=%ds)", PING_INTERVAL)
    yield
    task.cancel()
    log.info("=== Terver API shutting down ===")


app = FastAPI(title="Terver API", lifespan=lifespan)

origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = time.perf_counter()
    content_type = request.headers.get("content-type", "")
    log.info(
        "REQUEST  %s %s | content-type=%s | client=%s",
        request.method,
        request.url.path,
        content_type[:80],
        request.client.host if request.client else "unknown",
    )

    response = await call_next(request)

    elapsed = (time.perf_counter() - start) * 1000
    log.info(
        "RESPONSE %s %s | status=%d | %.0fms",
        request.method,
        request.url.path,
        response.status_code,
        elapsed,
    )
    return response


app.include_router(analyze_router)
app.include_router(analyze_case_router)
app.include_router(chat_router)


@app.get("/health")
def health():
    log.debug("Health check")
    return {"status": "ok"}
