"""Rank clauses with Postgres full text, then keep the same shortlist caps as the chat."""

import logging
import re
from dataclasses import dataclass

from sqlalchemy import func, literal_column, select
from sqlalchemy.orm import Session

from knowledge.models import Clause, Document, GlossaryAlias, Section
from knowledge.parse import CASE_SENSITIVE_ABBREVIATIONS

logger = logging.getLogger(__name__)

TOP_K = 8
MIN_SCORE_RATIO = 0.4
MAX_CONTEXT_CHARS = 18_000
_CANDIDATES = 30
_RUSSIAN = literal_column("'russian'")


@dataclass(frozen=True)
class Hit:
    document: str
    heading: str
    body: str
    document_id: str
    section_id: str
    anchor: str
    clause_id: str
    position: int
    score: float

    @property
    def path(self) -> str:
        return f"/kb/{self.document_id}#{self.anchor}"


def search_clauses(
    session: Session,
    question: str,
    document_ids: list[str] | None = None,
) -> list[Hit]:
    expanded = _expand(session, question)
    query = _or_tsquery(expanded)
    if query is None:
        return []
    if document_ids is not None and not document_ids:
        return []
    score = func.ts_rank_cd(Clause.search_vector, query).label("score")
    statement = (
        select(
            Clause.document_id,
            Clause.section_id,
            Clause.clause_id,
            Clause.position,
            Clause.body_markdown,
            Section.heading,
            Section.anchor,
            Document.title,
            score,
        )
        .join(
            Section,
            (Section.document_id == Clause.document_id) & (Section.section_id == Clause.section_id),
        )
        .join(Document, Document.id == Clause.document_id)
        .where(Clause.search_vector.op("@@")(query))
        .order_by(score.desc())
        .limit(_CANDIDATES)
    )
    if document_ids is not None:
        statement = statement.where(Clause.document_id.in_(document_ids))
    rows = session.execute(statement).all()
    if not rows:
        return []
    ranked = [_hit(row) for row in rows]
    best = ranked[0].score
    if best <= 0:
        return []
    selected: list[Hit] = []
    size = 0
    for hit in ranked:
        if hit.score < best * MIN_SCORE_RATIO:
            break
        if selected and size + len(hit.body) > MAX_CONTEXT_CHARS:
            break
        selected.append(hit)
        size += len(hit.body)
        if len(selected) >= TOP_K:
            break
    kept = _with_neighbors(session, selected)
    logger.info(
        "search %r -> %s",
        question[:180],
        "; ".join(f"{hit.document_id}/{hit.clause_id}" for hit in kept) or "none",
    )
    return kept


def _hit(row: object) -> Hit:
    document_id, section_id, clause_id, position, body, heading, anchor, title, score = row
    return Hit(
        document=title,
        heading=heading,
        body=body,
        document_id=document_id,
        section_id=section_id,
        anchor=anchor,
        clause_id=clause_id,
        position=position,
        score=float(score),
    )


def _with_neighbors(session: Session, selected: list[Hit]) -> list[Hit]:
    if not selected:
        return []
    seen = {(hit.document_id, hit.section_id, hit.clause_id) for hit in selected}
    adjacent: list[Hit] = []
    for hit in selected[:2]:
        for delta in (-1, 1):
            neighbor = _clause_at(session, hit.document_id, hit.section_id, hit.position + delta)
            if neighbor is None:
                continue
            key = (neighbor.document_id, neighbor.section_id, neighbor.clause_id)
            if key in seen:
                continue
            seen.add(key)
            adjacent.append(
                Hit(
                    document=neighbor.document,
                    heading=neighbor.heading,
                    body=neighbor.body,
                    document_id=neighbor.document_id,
                    section_id=neighbor.section_id,
                    anchor=neighbor.anchor,
                    clause_id=neighbor.clause_id,
                    position=neighbor.position,
                    score=hit.score * MIN_SCORE_RATIO,
                )
            )
    merged = [selected[0], *adjacent, *selected[1:]]
    kept: list[Hit] = []
    size = 0
    for hit in merged:
        if kept and size + len(hit.body) > MAX_CONTEXT_CHARS:
            continue
        kept.append(hit)
        size += len(hit.body)
        if len(kept) >= TOP_K:
            break
    return kept


def _clause_at(session: Session, document_id: str, section_id: str, position: int) -> Hit | None:
    if position < 0:
        return None
    row = session.execute(
        select(
            Clause.document_id,
            Clause.section_id,
            Clause.clause_id,
            Clause.position,
            Clause.body_markdown,
            Section.heading,
            Section.anchor,
            Document.title,
        )
        .join(
            Section,
            (Section.document_id == Clause.document_id) & (Section.section_id == Clause.section_id),
        )
        .join(Document, Document.id == Clause.document_id)
        .where(
            Clause.document_id == document_id,
            Clause.section_id == section_id,
            Clause.position == position,
        )
    ).one_or_none()
    if row is None:
        return None
    document_id, section_id, clause_id, position, body, heading, anchor, title = row
    return Hit(
        document=title,
        heading=heading,
        body=body,
        document_id=document_id,
        section_id=section_id,
        anchor=anchor,
        clause_id=clause_id,
        position=position,
        score=0,
    )


def _or_tsquery(text: str):
    """Match a clause when any query word hits.

    `websearch_to_tsquery` ANDs the words, so a full question would miss a clause
    that only shares the terms that matter. The old ranker added a score per term.
    """
    words: list[str] = []
    seen: set[str] = set()
    for word in re.findall(r"[0-9A-Za-zА-Яа-яЁё]+(?:-[0-9A-Za-zА-Яа-яЁё]+)*", text):
        key = word.casefold()
        if key in seen:
            continue
        seen.add(key)
        words.append(word)
        if len(words) >= 48:
            break
    if not words:
        return None
    query = func.plainto_tsquery(_RUSSIAN, words[0])
    for word in words[1:]:
        query = query.op("||")(func.plainto_tsquery(_RUSSIAN, word))
    return query


def _expand(session: Session, question: str) -> str:
    text = question.strip()
    if not text:
        return ""
    extra: list[str] = []
    aliases = session.scalars(select(GlossaryAlias)).all()
    for alias in aliases:
        phrases = tuple(alias.phrases)
        if any(_phrase_in(phrase, text, alias) for phrase in phrases):
            extra.extend(phrases)
    if not extra:
        return text
    return f"{text} {' '.join(extra)}"


def _phrase_in(phrase: str, question: str, alias: GlossaryAlias) -> bool:
    parts = phrase.split()
    if not parts:
        return False
    body = r"\s+".join(re.escape(part) for part in parts)
    case_sensitive = phrase in CASE_SENSITIVE_ABBREVIATIONS or (
        phrase == alias.abbreviation and alias.case_sensitive
    )
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.search(rf"(?<!\w){body}(?!\w)", question, flags) is not None
