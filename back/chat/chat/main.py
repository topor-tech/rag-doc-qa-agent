import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAIError
from pydantic import BaseModel, Field, field_validator

from chat.llm import complete, get_client
from chat.sessions import Session, SessionStore

logger = logging.getLogger(__name__)
store = SessionStore()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_client()
    yield


app = FastAPI(title="Chat", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=8000)

    @field_validator("content")
    @classmethod
    def not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content is empty")
        return stripped


class MessageOut(BaseModel):
    role: str
    content: str


class SessionOut(BaseModel):
    id: str
    messages: list[MessageOut]


def to_out(session: Session) -> SessionOut:
    return SessionOut(
        id=session.id,
        messages=[MessageOut(role=item.role, content=item.content) for item in session.messages],
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/sessions", response_model=SessionOut)
def create_session() -> SessionOut:
    return to_out(store.create())


@app.get("/sessions/{session_id}", response_model=SessionOut)
def read_session(session_id: str) -> SessionOut:
    session = store.snapshot(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    return to_out(session)


@app.post("/sessions/{session_id}/messages", response_model=SessionOut)
def post_message(session_id: str, body: MessageIn) -> SessionOut:
    session = store.add_message(session_id, "user", body.content)
    if session is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    history = [{"role": item.role, "content": item.content} for item in session.messages]
    try:
        reply = complete(history)
    except OpenAIError as exc:
        logger.exception("LLM request failed")
        raise HTTPException(status_code=502, detail="Не удалось получить ответ модели") from exc
    if not reply.strip():
        raise HTTPException(status_code=502, detail="Модель вернула пустой ответ")

    updated = store.add_message(session_id, "assistant", reply.strip())
    if updated is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    return to_out(updated)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
