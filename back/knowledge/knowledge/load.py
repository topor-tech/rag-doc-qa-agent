"""Replace one markdown file at a time when its bytes change."""

import hashlib
import logging
import os
from pathlib import Path

from sqlalchemy import delete, func, insert, literal_column
from sqlalchemy.orm import Session

from knowledge.db import session_scope
from knowledge.models import Clause, Document, GlossaryAlias, Section
from knowledge.parse import GLOSSARY_NAME, ParsedDocument, parse_document

logger = logging.getLogger(__name__)

_RUSSIAN = literal_column("'russian'")
_WEIGHT_A = literal_column("'A'")
_WEIGHT_B = literal_column("'B'")
_WEIGHT_C = literal_column("'C'")


def knowledge_dir() -> Path:
    configured = os.environ.get("KNOWLEDGE_DIR")
    if configured:
        path = Path(configured)
        if not path.is_dir():
            raise RuntimeError(f"KNOWLEDGE_DIR does not exist: {path}")
        return path
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data" / "knowlage_files"
        if candidate.is_dir():
            return candidate
    raise RuntimeError("knowledge directory not found; set KNOWLEDGE_DIR")


def load_knowledge(directory: Path | None = None) -> None:
    folder = directory or knowledge_dir()
    glossary_path = folder / GLOSSARY_NAME
    if not glossary_path.is_file():
        raise RuntimeError(f"glossary not found: {glossary_path}")
    regulations = sorted(path for path in folder.glob("*.md") if path.name != GLOSSARY_NAME)
    if not regulations:
        raise RuntimeError(f"no regulation markdown in {folder}")
    files = [glossary_path, *regulations]
    with session_scope() as session:
        for path in files:
            _upsert(session, path)
        names = [path.name for path in files]
        session.execute(delete(Document).where(Document.source_name.not_in(names)))
    logger.info("knowledge catalog is loaded from %s", folder)


def _upsert(session: Session, path: Path) -> None:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    existing = session.get(Document, _document_id(path.name))
    if existing is not None and existing.content_sha256 == digest:
        logger.info("unchanged %s", path.name)
        return
    parsed = parse_document(raw.decode("utf-8"), path.name)
    if existing is not None:
        session.execute(delete(Document).where(Document.id == parsed.id))
        session.flush()
        session.expunge_all()
    session.add(
        Document(
            id=parsed.id,
            kind=parsed.kind,
            title=parsed.title,
            source_name=parsed.source_name,
            source_markdown=parsed.source_markdown,
            content_sha256=digest,
        )
    )
    for section in parsed.sections:
        session.add(
            Section(
                document_id=parsed.id,
                section_id=section.section_id,
                position=section.position,
                heading=section.heading,
                anchor=section.anchor,
                body_markdown=section.body,
            )
        )
    session.flush()
    _insert_clauses(session, parsed)
    if parsed.kind == "glossary":
        session.execute(delete(GlossaryAlias))
        session.add_all(
            GlossaryAlias(
                abbreviation=alias.abbreviation,
                phrases=list(alias.phrases),
                case_sensitive=alias.case_sensitive,
            )
            for alias in parsed.aliases
        )
    logger.info("loaded %s (%s sections)", path.name, len(parsed.sections))


def _insert_clauses(session: Session, parsed: ParsedDocument) -> None:
    if parsed.kind != "regulation":
        return
    for section in parsed.sections:
        for clause in section.clauses:
            session.execute(
                insert(Clause).values(
                    document_id=parsed.id,
                    section_id=section.section_id,
                    clause_id=clause.clause_id,
                    position=clause.position,
                    body_markdown=clause.body,
                    search_vector=_search_vector(
                        section.heading, clause.clause_id, parsed.title, clause.body
                    ),
                )
            )


def _search_vector(heading: str, clause_id: str, title: str, body: str):
    def weighted(text: str, weight):
        return func.setweight(func.to_tsvector(_RUSSIAN, text), weight)

    return (
        weighted(heading, _WEIGHT_A)
        .op("||")(weighted(clause_id, _WEIGHT_A))
        .op("||")(weighted(title, _WEIGHT_B))
        .op("||")(weighted(body or " ", _WEIGHT_C))
    )


def _document_id(source_name: str) -> str:
    if source_name == GLOSSARY_NAME:
        return "glossary"
    return source_name.removesuffix(".md")
