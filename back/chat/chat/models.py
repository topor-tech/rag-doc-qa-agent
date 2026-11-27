"""Tables in the `chat` schema."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    desc,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Visitor(Base):
    __tablename__ = "visitors"
    __table_args__ = ({"schema": "chat"},)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=text("uuidv7()"))
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(
            "title is null or char_length(title) between 1 and 80",
            name="sessions_title_length",
        ),
        Index("sessions_owner_updated_idx", "owner_id", desc("updated_at")),
        {"schema": "chat"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=text("uuidv7()"))
    owner_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("chat.visitors.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    title: Mapped[str | None] = mapped_column(Text)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("position >= 0", name="messages_position_nonnegative"),
        CheckConstraint("role in ('user', 'assistant')", name="messages_role"),
        CheckConstraint("char_length(content) > 0", name="messages_content_nonempty"),
        UniqueConstraint("session_id", "position", name="messages_session_position"),
        {"schema": "chat"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=text("uuidv7()"))
    session_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("chat.sessions.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TurnLog(Base):
    __tablename__ = "turn_logs"
    __table_args__ = (
        CheckConstraint("position >= 0", name="turn_logs_position_nonnegative"),
        CheckConstraint("format_version >= 1", name="turn_logs_format_version"),
        UniqueConstraint("session_id", "position", name="turn_logs_session_position"),
        {"schema": "chat"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=text("uuidv7()"))
    session_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("chat.sessions.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer)
    user_message_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("chat.messages.id", ondelete="CASCADE")
    )
    assistant_message_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("chat.messages.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    format_version: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
