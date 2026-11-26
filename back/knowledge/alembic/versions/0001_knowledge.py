"""Knowledge catalog tables.

Revision ID: 0001_knowledge
Revises:
Create Date: 2026-11-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_knowledge"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("create schema if not exists knowledge")
    op.create_table(
        "documents",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("source_markdown", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column(
            "loaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("kind in ('regulation', 'glossary')", name="documents_kind"),
        sa.PrimaryKeyConstraint("id"),
        schema="knowledge",
    )
    op.create_table(
        "sections",
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("section_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("heading", sa.Text(), nullable=False),
        sa.Column("anchor", sa.Text(), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.CheckConstraint("position >= 0", name="sections_position_nonnegative"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge.documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_id", "section_id"),
        sa.UniqueConstraint("document_id", "position", name="sections_document_position"),
        schema="knowledge",
    )
    op.create_table(
        "clauses",
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("section_id", sa.Text(), nullable=False),
        sa.Column("clause_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=False),
        sa.CheckConstraint("position >= 0", name="clauses_position_nonnegative"),
        sa.ForeignKeyConstraint(
            ["document_id", "section_id"],
            ["knowledge.sections.document_id", "knowledge.sections.section_id"],
            ondelete="CASCADE",
            name="clauses_section_fkey",
        ),
        sa.PrimaryKeyConstraint("document_id", "section_id", "clause_id"),
        sa.UniqueConstraint(
            "document_id", "section_id", "position", name="clauses_section_position"
        ),
        schema="knowledge",
    )
    op.create_index(
        "clauses_search_idx",
        "clauses",
        ["search_vector"],
        unique=False,
        schema="knowledge",
        postgresql_using="gin",
    )
    op.create_table(
        "glossary_aliases",
        sa.Column("abbreviation", sa.Text(), nullable=False),
        sa.Column("phrases", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("case_sensitive", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("abbreviation"),
        schema="knowledge",
    )


def downgrade() -> None:
    op.drop_index("clauses_search_idx", table_name="clauses", schema="knowledge")
    op.drop_table("glossary_aliases", schema="knowledge")
    op.drop_table("clauses", schema="knowledge")
    op.drop_table("sections", schema="knowledge")
    op.drop_table("documents", schema="knowledge")
    op.execute("drop schema if exists knowledge")
