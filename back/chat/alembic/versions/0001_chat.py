"""Chat visitors, sessions, messages, and turn logs.

Revision ID: 0001_chat
Revises:
Create Date: 2026-11-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_chat"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("create schema if not exists chat")
    op.create_table(
        "visitors",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
        schema="chat",
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "title is null or char_length(title) between 1 and 80",
            name="sessions_title_length",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["chat.visitors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="chat",
    )
    op.execute(
        "create index sessions_owner_updated_idx on chat.sessions (owner_id, updated_at desc)"
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("position >= 0", name="messages_position_nonnegative"),
        sa.CheckConstraint("role in ('user', 'assistant')", name="messages_role"),
        sa.CheckConstraint("char_length(content) > 0", name="messages_content_nonempty"),
        sa.ForeignKeyConstraint(["session_id"], ["chat.sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "position", name="messages_session_position"),
        schema="chat",
    )
    op.create_table(
        "turn_logs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("user_message_id", sa.Uuid(), nullable=False),
        sa.Column("assistant_message_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("format_version", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint("position >= 0", name="turn_logs_position_nonnegative"),
        sa.CheckConstraint("format_version >= 1", name="turn_logs_format_version"),
        sa.ForeignKeyConstraint(["session_id"], ["chat.sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_message_id"], ["chat.messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assistant_message_id"], ["chat.messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "position", name="turn_logs_session_position"),
        schema="chat",
    )


def downgrade() -> None:
    op.drop_table("turn_logs", schema="chat")
    op.drop_table("messages", schema="chat")
    op.drop_index("sessions_owner_updated_idx", table_name="sessions", schema="chat")
    op.drop_table("sessions", schema="chat")
    op.drop_table("visitors", schema="chat")
    op.execute("drop schema if exists chat")
