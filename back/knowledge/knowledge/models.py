"""Tables in the `knowledge` schema. Primary keys are the public catalog ids."""

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("kind in ('regulation', 'glossary')", name="documents_kind"),
        {"schema": "knowledge"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    source_name: Mapped[str] = mapped_column(Text)
    source_markdown: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(Text)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Section(Base):
    __tablename__ = "sections"
    __table_args__ = (
        CheckConstraint("position >= 0", name="sections_position_nonnegative"),
        UniqueConstraint("document_id", "position", name="sections_document_position"),
        {"schema": "knowledge"},
    )

    document_id: Mapped[str] = mapped_column(
        Text, ForeignKey("knowledge.documents.id", ondelete="CASCADE"), primary_key=True
    )
    section_id: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(Text)
    anchor: Mapped[str] = mapped_column(Text)
    body_markdown: Mapped[str] = mapped_column(Text)


class Clause(Base):
    __tablename__ = "clauses"
    __table_args__ = (
        CheckConstraint("position >= 0", name="clauses_position_nonnegative"),
        UniqueConstraint("document_id", "section_id", "position", name="clauses_section_position"),
        ForeignKeyConstraint(
            ["document_id", "section_id"],
            ["knowledge.sections.document_id", "knowledge.sections.section_id"],
            ondelete="CASCADE",
            name="clauses_section_fkey",
        ),
        {"schema": "knowledge"},
    )

    document_id: Mapped[str] = mapped_column(Text, primary_key=True)
    section_id: Mapped[str] = mapped_column(Text, primary_key=True)
    clause_id: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    body_markdown: Mapped[str] = mapped_column(Text)
    lemma_text: Mapped[str | None] = mapped_column(Text)
    search_vector: Mapped[str] = mapped_column(TSVECTOR)


class GlossaryAlias(Base):
    __tablename__ = "glossary_aliases"
    __table_args__: ClassVar[dict[str, Any]] = {"schema": "knowledge"}

    abbreviation: Mapped[str] = mapped_column(Text, primary_key=True)
    phrases: Mapped[list[str]] = mapped_column(ARRAY(Text))
    case_sensitive: Mapped[bool] = mapped_column()
