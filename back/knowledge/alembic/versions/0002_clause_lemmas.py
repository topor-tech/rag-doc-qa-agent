"""Store pymorphy3 lemmas next to each clause body.

Revision ID: 0002_clause_lemmas
Revises: 0001_knowledge
Create Date: 2026-11-27

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_clause_lemmas"
down_revision: str | None = "0001_knowledge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "clauses",
        sa.Column("lemma_text", sa.Text(), nullable=True),
        schema="knowledge",
    )


def downgrade() -> None:
    op.drop_column("clauses", "lemma_text", schema="knowledge")
