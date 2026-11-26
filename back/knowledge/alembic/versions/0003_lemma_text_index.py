"""Index lemmatized clause bodies and rebuild the weighted vector.

Revision ID: 0003_lemma_text_index
Revises: 0002_clause_lemmas
Create Date: 2026-11-27

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_lemma_text_index"
down_revision: str | None = "0002_clause_lemmas"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        create index clauses_lemma_text_idx
            on knowledge.clauses
            using gin (to_tsvector('simple', coalesce(lemma_text, '')))
        """
    )
    op.execute("update knowledge.clauses set lemma_text = null")


def downgrade() -> None:
    op.execute("drop index if exists knowledge.clauses_lemma_text_idx")
    op.execute("update knowledge.clauses set lemma_text = null")
