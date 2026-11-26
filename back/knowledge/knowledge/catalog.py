"""Primary-key reads shared by HTTP and MCP."""

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge.models import Document, Section
from knowledge.parse import CASE_SENSITIVE_ABBREVIATIONS, GLOSSARY_ID
from knowledge.search import Hit, search_clauses


@dataclass(frozen=True)
class SectionView:
    document_id: str
    document_title: str
    source_name: str
    section_id: str
    heading: str
    anchor: str
    body: str

    @property
    def path(self) -> str:
        return f"/kb/{self.document_id}#{self.anchor}"


@dataclass(frozen=True)
class DocumentView:
    id: str
    kind: str
    title: str
    source_name: str
    source_markdown: str
    sections: tuple[SectionView, ...]

    @property
    def path(self) -> str:
        return f"/kb/{self.id}"


@dataclass(frozen=True)
class PromptDocument:
    id: str
    title: str
    path: str


@dataclass(frozen=True)
class PromptContext:
    glossary: str
    regulations: tuple[PromptDocument, ...]
    catalog: tuple[PromptDocument, ...]
    headings: tuple[str, ...]
    aliases: str


def list_regulations(session: Session) -> list[DocumentView]:
    rows = session.scalars(
        select(Document).where(Document.kind == "regulation").order_by(Document.source_name)
    ).all()
    return [_document(session, row) for row in rows]


def list_catalog(session: Session) -> list[DocumentView]:
    regulations = list_regulations(session)
    glossary = find_document(session, GLOSSARY_ID)
    if glossary is None:
        return regulations
    return [*regulations, glossary]


def find_document(session: Session, document_id: str) -> DocumentView | None:
    row = session.get(Document, document_id)
    if row is None:
        return None
    return _document(session, row)


def find_section(session: Session, document_id: str, section_id: str) -> SectionView | None:
    row = session.get(Section, (document_id, section_id))
    if row is None:
        return None
    document = session.get(Document, document_id)
    if document is None:
        return None
    return _section(document, row)


def find_glossary_term(session: Session, term: str) -> SectionView | None:
    text = term.strip()
    if not text:
        return None
    direct = find_section(session, GLOSSARY_ID, text)
    if direct is not None:
        return direct
    folded = text.casefold()
    document = find_document(session, GLOSSARY_ID)
    if document is None:
        return None
    for section in document.sections:
        if section.section_id in CASE_SENSITIVE_ABBREVIATIONS:
            continue
        if section.section_id.casefold() == folded:
            return section
    return None


def document_markdown(document: DocumentView) -> str:
    if document.kind == "glossary":
        return document.source_markdown.strip()
    parts = [f"# {document.title}"]
    for section in document.sections:
        if section.section_id == "intro":
            parts.append(section.body)
            continue
        block = f"## {section.heading}"
        if section.body:
            block = f"{block}\n\n{section.body}"
        parts.append(block)
    return "\n\n".join(parts)


def section_snippet(body: str, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", body).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def search_sections(session: Session, question: str) -> list[tuple[SectionView, float]]:
    found: list[tuple[SectionView, float]] = []
    seen: set[tuple[str, str]] = set()
    for hit in search_clauses(session, question):
        key = (hit.document_id, hit.section_id)
        if key in seen:
            continue
        seen.add(key)
        section = find_section(session, hit.document_id, hit.section_id)
        if section is None:
            continue
        found.append((section, hit.score))
    return found


def prompt_context(session: Session) -> PromptContext:
    regulations = list_regulations(session)
    glossary = find_document(session, GLOSSARY_ID)
    if glossary is None:
        raise RuntimeError("glossary is not loaded")
    regulation_docs = tuple(
        PromptDocument(id=document.id, title=document.title, path=document.path)
        for document in regulations
    )
    glossary_doc = PromptDocument(id=glossary.id, title=glossary.title, path=glossary.path)
    headings = tuple(section.heading for document in regulations for section in document.sections)
    aliases = "\n".join(
        line.strip()
        for line in glossary.source_markdown.splitlines()
        if "=" in line and not line.strip().startswith("#")
    )
    return PromptContext(
        glossary=glossary.source_markdown.strip(),
        regulations=regulation_docs,
        catalog=(*regulation_docs, glossary_doc),
        headings=headings,
        aliases=aliases,
    )


def _document(session: Session, row: Document) -> DocumentView:
    sections = session.scalars(
        select(Section).where(Section.document_id == row.id).order_by(Section.position)
    ).all()
    return DocumentView(
        id=row.id,
        kind=row.kind,
        title=row.title,
        source_name=row.source_name,
        source_markdown=row.source_markdown,
        sections=tuple(_section(row, section) for section in sections),
    )


def _section(document: Document, row: Section) -> SectionView:
    return SectionView(
        document_id=document.id,
        document_title=document.title,
        source_name=document.source_name,
        section_id=row.section_id,
        heading=row.heading,
        anchor=row.anchor,
        body=row.body_markdown,
    )


def clause_payload(hit: Hit) -> dict[str, str | float]:
    return {
        "document": hit.document,
        "heading": hit.heading,
        "body": hit.body,
        "document_id": hit.document_id,
        "section_id": hit.section_id,
        "anchor": hit.anchor,
        "clause_id": hit.clause_id,
        "path": hit.path,
        "score": hit.score,
    }
