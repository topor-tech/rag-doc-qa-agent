"""Visitors, dialogues, and turn logs in Postgres."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from chat.db import session_scope
from chat.llm import FORMAT_VERSION, TurnDebug, turn_payload
from chat.models import ChatSession, Message, TurnLog, Visitor

TITLE_LIMIT = 80


class SessionNotFoundError(Exception):
    pass


class SessionReadOnlyError(Exception):
    pass


@dataclass(frozen=True)
class StoredMessage:
    id: UUID
    role: str
    content: str


@dataclass(frozen=True)
class StoredSession:
    id: UUID
    title: str | None
    owner_id: UUID
    messages: tuple[StoredMessage, ...]


@dataclass(frozen=True)
class StoredSessionSummary:
    id: UUID
    title: str | None
    updated_at: datetime


@dataclass(frozen=True)
class StoredTurn:
    id: UUID
    position: int
    user_message_id: UUID
    assistant_message_id: UUID | None
    created_at: datetime
    format_version: int
    payload: dict[str, Any]


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session_title(content: str) -> str:
    return " ".join(content.split())[:TITLE_LIMIT]


def resolve_visitor(raw_token: str | None) -> tuple[UUID, str | None]:
    """Return the visitor id and a cookie value when the browser needs a new one."""
    with session_scope() as db:
        if raw_token:
            found = db.scalar(select(Visitor).where(Visitor.token_hash == hash_token(raw_token)))
            if found is not None:
                return found.id, None
        token = secrets.token_urlsafe(32)
        visitor = Visitor(token_hash=hash_token(token))
        db.add(visitor)
        db.flush()
        db.refresh(visitor)
        return visitor.id, token


def list_sessions(visitor_id: UUID) -> list[StoredSessionSummary]:
    with session_scope() as db:
        rows = db.scalars(
            select(ChatSession)
            .where(ChatSession.owner_id == visitor_id)
            .order_by(ChatSession.updated_at.desc())
        ).all()
        return [
            StoredSessionSummary(id=row.id, title=row.title, updated_at=row.updated_at)
            for row in rows
        ]


def create_session(visitor_id: UUID) -> StoredSession:
    with session_scope() as db:
        row = ChatSession(owner_id=visitor_id)
        db.add(row)
        db.flush()
        db.refresh(row)
        return StoredSession(id=row.id, title=row.title, owner_id=row.owner_id, messages=())


def read_session(session_id: UUID) -> StoredSession | None:
    with session_scope() as db:
        row = db.get(ChatSession, session_id)
        if row is None:
            return None
        messages = db.scalars(
            select(Message).where(Message.session_id == session_id).order_by(Message.position)
        ).all()
        return StoredSession(
            id=row.id,
            title=row.title,
            owner_id=row.owner_id,
            messages=tuple(
                StoredMessage(id=item.id, role=item.role, content=item.content) for item in messages
            ),
        )


def read_turn_logs(session_id: UUID, visitor_id: UUID) -> list[StoredTurn]:
    with session_scope() as db:
        row = _session_row(db, session_id)
        if row.owner_id != visitor_id:
            raise SessionReadOnlyError
        logs = db.scalars(
            select(TurnLog).where(TurnLog.session_id == session_id).order_by(TurnLog.position)
        ).all()
        return [_stored_turn(item) for item in logs]


def transcript(session_id: UUID) -> list[dict[str, str]]:
    with session_scope() as db:
        rows = db.scalars(
            select(Message).where(Message.session_id == session_id).order_by(Message.position)
        ).all()
        return [{"role": item.role, "content": item.content} for item in rows]


def append_user_message(session_id: UUID, visitor_id: UUID, content: str) -> UUID:
    with session_scope() as db:
        row = _lock_owned(db, session_id, visitor_id)
        message = Message(
            session_id=session_id,
            position=_next_message_position(db, session_id),
            role="user",
            content=content,
        )
        db.add(message)
        if row.title is None:
            title = session_title(content)
            if title:
                row.title = title
        row.updated_at = datetime.now(UTC)
        db.flush()
        db.refresh(message)
        return message.id


def append_assistant_turn(
    session_id: UUID,
    visitor_id: UUID,
    user_message_id: UUID,
    reply: str,
    debug: TurnDebug,
) -> None:
    with session_scope() as db:
        _lock_owned(db, session_id, visitor_id)
        _require_user_message(db, session_id, user_message_id)
        assistant = Message(
            session_id=session_id,
            position=_next_message_position(db, session_id),
            role="assistant",
            content=reply,
        )
        db.add(assistant)
        db.flush()
        db.refresh(assistant)
        db.add(
            TurnLog(
                session_id=session_id,
                position=_next_turn_position(db, session_id),
                user_message_id=user_message_id,
                assistant_message_id=assistant.id,
                format_version=FORMAT_VERSION,
                payload=turn_payload(debug, None),
            )
        )
        dialogue = db.get(ChatSession, session_id)
        if dialogue is None:
            raise SessionNotFoundError
        dialogue.updated_at = datetime.now(UTC)


def append_failed_turn(
    session_id: UUID,
    visitor_id: UUID,
    user_message_id: UUID,
    debug: TurnDebug,
    error: str,
) -> None:
    with session_scope() as db:
        _lock_owned(db, session_id, visitor_id)
        _require_user_message(db, session_id, user_message_id)
        db.add(
            TurnLog(
                session_id=session_id,
                position=_next_turn_position(db, session_id),
                user_message_id=user_message_id,
                assistant_message_id=None,
                format_version=FORMAT_VERSION,
                payload=turn_payload(debug, error),
            )
        )
        dialogue = db.get(ChatSession, session_id)
        if dialogue is None:
            raise SessionNotFoundError
        dialogue.updated_at = datetime.now(UTC)


def _session_row(db: DbSession, session_id: UUID) -> ChatSession:
    row = db.get(ChatSession, session_id)
    if row is None:
        raise SessionNotFoundError
    return row


def _lock_owned(db: DbSession, session_id: UUID, visitor_id: UUID) -> ChatSession:
    row = db.scalar(select(ChatSession).where(ChatSession.id == session_id).with_for_update())
    if row is None:
        raise SessionNotFoundError
    if row.owner_id != visitor_id:
        raise SessionReadOnlyError
    return row


def _require_user_message(db: DbSession, session_id: UUID, message_id: UUID) -> None:
    message = db.get(Message, message_id)
    if message is None or message.session_id != session_id or message.role != "user":
        raise SessionNotFoundError


def _next_message_position(db: DbSession, session_id: UUID) -> int:
    current = db.scalar(select(func.max(Message.position)).where(Message.session_id == session_id))
    if current is None:
        return 0
    return current + 1


def _next_turn_position(db: DbSession, session_id: UUID) -> int:
    current = db.scalar(select(func.max(TurnLog.position)).where(TurnLog.session_id == session_id))
    if current is None:
        return 0
    return current + 1


def _stored_turn(row: TurnLog) -> StoredTurn:
    payload = row.payload if isinstance(row.payload, dict) else {}
    return StoredTurn(
        id=row.id,
        position=row.position,
        user_message_id=row.user_message_id,
        assistant_message_id=row.assistant_message_id,
        created_at=row.created_at,
        format_version=row.format_version,
        payload=payload,
    )
