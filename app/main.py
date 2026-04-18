import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from app.api.analyze import router as analyze_router
from app.api.analyze_case import router as analyze_case_router
from app.api.chat import router as chat_router
from app.agents.memory import ensure_tables_exist

PING_INTERVAL = 290  # 4 min 50 sec — keeps Render free tier awake


async def _self_ping():
    try:
        import httpx
        url = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:8000") + "/health"
        async with httpx.AsyncClient(timeout=10) as client:
            while True:
                await asyncio.sleep(PING_INTERVAL)
                try:
                    await client.get(url)
                except Exception:
                    pass
    except ImportError:
        pass  # httpx not available, skip self-ping


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        ensure_tables_exist()
        print("INFO: Database tables ready.")
    except Exception as e:
        print(f"WARNING: DB init failed ({e}). Chat persistence disabled — set DATABASE_URL to enable.")

    task = asyncio.create_task(_self_ping())
    yield
    task.cancel()


app = FastAPI(title="Terver API", lifespan=lifespan)

origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze_router)
app.include_router(analyze_case_router)
app.include_router(chat_router)


@app.get("/health")
def health():
    return {"status": "ok"}
