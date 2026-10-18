"""FastAPI приложение агента.

POST /chat   — основной эндпоинт {message, history?} -> {response, ...}
GET  /health — проверка живости
GET  /mode   — текущий режим (vulnerable/protected)
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from . import config
from . import db
from . import llm
from . import agent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting agent in %s mode (model=%s)", config.AGENT_MODE, config.MODEL)
    db.init_db()
    logger.info("Database initialized at %s", config.DB_PATH)
    llm.ensure_model()
    yield
    logger.info("Agent shutting down")


app = FastAPI(title="QA Assistant Agent", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str
    history: list[dict] | None = None


class ChatResponse(BaseModel):
    response: str
    mode: str
    tools_used: list
    blocked_by_input_guard: bool = False
    output_redacted: bool = False
    iterations: int = 0


@app.get("/health")
def health():
    return {"status": "ok", "mode": config.AGENT_MODE, "model": config.MODEL}


@app.get("/mode")
def mode():
    return {"mode": config.AGENT_MODE}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    result = agent.run_agent(req.message, req.history)
    return ChatResponse(**result)
