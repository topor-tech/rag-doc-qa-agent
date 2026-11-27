"""Chat API. Sessions live in Postgres and are owned by a visitor cookie."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, NoReturn
from uuid import UUID

from alembic.config import Config
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAIError
from pydantic import BaseModel, Field, field_validator

from alembic import command
from chat.db import database_url
from chat.kb_http import router as kb_router
from chat.knowledge import KnowledgeUnavailableError
from chat.llm import answer_turn, current_turn_debug, get_client
from chat.sessions import (
    SessionNotFoundError,
    SessionReadOnlyError,
    StoredSession,
    append_assistant_turn,
    append_failed_turn,
    append_user_message,
    create_session,
    list_sessions,
    read_session,
    read_turn_logs,
    resolve_visitor,
    transcript,
)

logger = logging.getLogger(__name__)

VISITOR_COOKIE = "chat_visitor"
COOKIE_MAX_AGE_SECONDS = 400 * 24 * 60 * 60


def upgrade() -> None:
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url())
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    upgrade()
    get_client()
    yield


app = FastAPI(title="Chat", lifespan=lifespan)
app.include_router(kb_router)
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
    id: str
    role: str
    content: str


class SessionOut(BaseModel):
    id: str
    title: str | None
    writable: bool
    messages: list[MessageOut]


class SessionSummaryOut(BaseModel):
    id: str
    title: str | None
    updated_at: datetime


class SessionListOut(BaseModel):
    sessions: list[SessionSummaryOut]


class TurnLogOut(BaseModel):
    id: str
    position: int
    user_message_id: str
    assistant_message_id: str | None
    created_at: datetime
    format_version: int
    payload: dict[str, Any]


class TurnLogListOut(BaseModel):
    turn_logs: list[TurnLogOut]


def current_visitor(request: Request, response: Response) -> UUID:
    visitor_id, token = resolve_visitor(request.cookies.get(VISITOR_COOKIE))
    if token is not None:
        response.set_cookie(
            key=VISITOR_COOKIE,
            value=token,
            max_age=COOKIE_MAX_AGE_SECONDS,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            path="/",
        )
    return visitor_id


def parse_session_id(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(status_code=404, detail="Сессия не найдена") from None


def raise_stored(exc: SessionNotFoundError | SessionReadOnlyError) -> NoReturn:
    if isinstance(exc, SessionNotFoundError):
        raise HTTPException(status_code=404, detail="Сессия не найдена") from exc
    raise HTTPException(status_code=403, detail="Этот диалог только для чтения") from exc


def to_out(session: StoredSession, visitor_id: UUID) -> SessionOut:
    return SessionOut(
        id=str(session.id),
        title=session.title,
        writable=session.owner_id == visitor_id,
        messages=[
            MessageOut(id=str(item.id), role=item.role, content=item.content)
            for item in session.messages
        ],
    )


def load_out(session_id: UUID, visitor_id: UUID) -> SessionOut:
    session = read_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    return to_out(session, visitor_id)


def remember_failure(
    session_id: UUID,
    visitor_id: UUID,
    user_message_id: UUID,
    detail: str,
) -> None:
    try:
        append_failed_turn(
            session_id,
            visitor_id,
            user_message_id,
            current_turn_debug(),
            detail,
        )
    except Exception:
        logger.exception("failed to store turn log")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/sessions", response_model=SessionListOut)
def list_visitor_sessions(visitor_id: Annotated[UUID, Depends(current_visitor)]) -> SessionListOut:
    rows = list_sessions(visitor_id)
    return SessionListOut(
        sessions=[
            SessionSummaryOut(id=str(row.id), title=row.title, updated_at=row.updated_at)
            for row in rows
        ]
    )


@app.post("/sessions", response_model=SessionOut)
def open_session(visitor_id: Annotated[UUID, Depends(current_visitor)]) -> SessionOut:
    return to_out(create_session(visitor_id), visitor_id)


@app.get("/sessions/{session_id}", response_model=SessionOut)
def read_one_session(
    session_id: str,
    visitor_id: Annotated[UUID, Depends(current_visitor)],
) -> SessionOut:
    return load_out(parse_session_id(session_id), visitor_id)


@app.get("/sessions/{session_id}/turn-logs", response_model=TurnLogListOut)
def read_one_turn_log(
    session_id: str,
    visitor_id: Annotated[UUID, Depends(current_visitor)],
) -> TurnLogListOut:
    try:
        rows = read_turn_logs(parse_session_id(session_id), visitor_id)
    except (SessionNotFoundError, SessionReadOnlyError) as exc:
        raise_stored(exc)
    return TurnLogListOut(
        turn_logs=[
            TurnLogOut(
                id=str(row.id),
                position=row.position,
                user_message_id=str(row.user_message_id),
                assistant_message_id=(
                    None if row.assistant_message_id is None else str(row.assistant_message_id)
                ),
                created_at=row.created_at,
                format_version=row.format_version,
                payload=row.payload,
            )
            for row in rows
        ]
    )


@app.post("/sessions/{session_id}/messages", response_model=SessionOut)
def post_message(
    session_id: str,
    body: MessageIn,
    visitor_id: Annotated[UUID, Depends(current_visitor)],
) -> SessionOut:
    dialogue_id = parse_session_id(session_id)
    try:
        user_message_id = append_user_message(dialogue_id, visitor_id, body.content)
    except (SessionNotFoundError, SessionReadOnlyError) as exc:
        raise_stored(exc)

    history = transcript(dialogue_id)
    try:
        result = answer_turn(history)
    except KnowledgeUnavailableError as exc:
        logger.exception("knowledge service request failed")
        detail = "База знаний недоступна"
        remember_failure(dialogue_id, visitor_id, user_message_id, detail)
        raise HTTPException(status_code=502, detail=detail) from exc
    except OpenAIError as exc:
        logger.exception("LLM request failed")
        detail = "Не удалось получить ответ модели"
        remember_failure(dialogue_id, visitor_id, user_message_id, detail)
        raise HTTPException(status_code=502, detail=detail) from exc
    if not result.reply.strip():
        detail = "Модель вернула пустой ответ"
        remember_failure(dialogue_id, visitor_id, user_message_id, detail)
        raise HTTPException(status_code=502, detail=detail)

    try:
        append_assistant_turn(
            dialogue_id,
            visitor_id,
            user_message_id,
            result.reply,
            result.debug,
        )
    except (SessionNotFoundError, SessionReadOnlyError) as exc:
        raise_stored(exc)
    return load_out(dialogue_id, visitor_id)


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
