import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from app.api.analyze import router as analyze_router
from app.api.chat import router as chat_router
from app.agents.memory import ensure_tables_exist


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        ensure_tables_exist()
        print("INFO: Database tables ready.")
    except Exception as e:
        print(f"WARNING: DB init failed ({e}). Chat persistence disabled — set DATABASE_URL to enable.")
    yield


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
app.include_router(chat_router)


@app.get("/health")
def health():
    return {"status": "ok"}
