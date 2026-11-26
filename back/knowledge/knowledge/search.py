"""Rank clauses with the same BM25 the chat used, over rows loaded from Postgres."""

import logging
import math
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge.models import Clause, Document, GlossaryAlias, Section
from knowledge.parse import CASE_SENSITIVE_ABBREVIATIONS

logger = logging.getLogger(__name__)

TOP_K = 8
MIN_SCORE_RATIO = 0.4
MAX_CONTEXT_CHARS = 18_000

_STOPWORDS = frozenset(
    {
        "и",
        "в",
        "во",
        "на",
        "по",
        "что",
        "как",
        "для",
        "это",
        "или",
        "не",
        "от",
        "к",
        "ко",
        "с",
        "со",
        "за",
        "из",
        "при",
        "ли",
        "же",
        "бы",
        "то",
        "а",
        "но",
        "да",
        "если",
        "когда",
        "где",
        "кто",
        "чем",
        "чтобы",
        "какой",
        "какая",
        "какие",
        "какое",
        "можно",
        "нужно",
        "надо",
        "мне",
        "меня",
        "его",
        "ее",
        "её",
        "их",
        "мы",
        "вы",
        "он",
        "она",
        "они",
        "этот",
        "эта",
        "эти",
        "тот",
        "та",
        "те",
        "уже",
        "ещё",
        "еще",
        "только",
        "также",
        "тоже",
        "над",
        "под",
        "без",
        "до",
        "после",
        "через",
        "между",
        "про",
        "об",
        "обо",
        "все",
        "всё",
        "очень",
        "просто",
        "сейчас",
        "потом",
        "тогда",
        "потому",
        "поэтому",
        "который",
        "которая",
        "которые",
        "которое",
        "быть",
        "был",
        "была",
        "были",
        "будет",
        "есть",
        "нет",
        "ну",
        "вот",
        "там",
        "тут",
        "the",
        "and",
        "for",
        "with",
    }
)
_SUFFIXES = (
    "иями",
    "ями",
    "ами",
    "ого",
    "ему",
    "ому",
    "ыми",
    "ими",
    "ою",
    "ею",
    "ая",
    "яя",
    "ое",
    "ее",
    "ые",
    "ие",
    "ую",
    "юю",
    "ой",
    "ый",
    "ий",
    "ых",
    "их",
    "ов",
    "ев",
    "ах",
    "ях",
    "ом",
    "ем",
    "ам",
    "ям",
    "ей",
    "а",
    "я",
    "ы",
    "и",
    "е",
    "у",
    "ю",
    "о",
)
_TOKEN = re.compile(r"[A-Za-zА-ЯЁа-яё0-9]+(?:-[A-Za-zА-ЯЁа-яё0-9]+)*")
_BM25_K1 = 1.5
_BM25_B = 0.75


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


@dataclass(frozen=True)
class _Row:
    document: str
    heading: str
    body: str
    document_id: str
    section_id: str
    anchor: str
    clause_id: str
    position: int


def search_clauses(
    session: Session,
    question: str,
    document_ids: list[str] | None = None,
) -> list[Hit]:
    if document_ids is not None and not document_ids:
        return []
    rows = _load_clauses(session, document_ids)
    if not rows:
        return []
    aliases = session.scalars(select(GlossaryAlias)).all()
    query_terms = _query_terms(question, aliases)
    if not query_terms:
        return []
    bags = tuple(_clause_terms(row) for row in rows)
    scores = _bm25(query_terms, bags)
    ranked = sorted(
        zip(scores, rows, bags, strict=True),
        key=lambda item: item[0],
        reverse=True,
    )
    best_score, _best_row, best_terms = ranked[0]
    if best_score <= 0 or not _overlap_ok(query_terms, best_terms):
        logger.info("search %r -> none", question[:180])
        return []
    selected: list[Hit] = []
    size = 0
    for score, row, _terms in ranked:
        if score < best_score * MIN_SCORE_RATIO:
            break
        if selected and size + len(row.body) > MAX_CONTEXT_CHARS:
            break
        selected.append(_hit(row, score))
        size += len(row.body)
        if len(selected) >= TOP_K:
            break
    kept = _with_neighbors(session, selected)
    logger.info(
        "search %r -> %s",
        question[:180],
        "; ".join(f"{hit.document_id}/{hit.clause_id}" for hit in kept) or "none",
    )
    return kept


def _load_clauses(session: Session, document_ids: list[str] | None) -> list[_Row]:
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
        )
        .join(
            Section,
            (Section.document_id == Clause.document_id) & (Section.section_id == Clause.section_id),
        )
        .join(Document, Document.id == Clause.document_id)
        .order_by(Document.id, Section.position, Clause.position)
    )
    if document_ids is not None:
        statement = statement.where(Clause.document_id.in_(document_ids))
    rows = session.execute(statement).all()
    loaded: list[_Row] = []
    for document_id, section_id, clause_id, position, body, heading, anchor, title in rows:
        loaded.append(
            _Row(
                document=title,
                heading=heading,
                body=body,
                document_id=document_id,
                section_id=section_id,
                anchor=anchor,
                clause_id=clause_id,
                position=position,
            )
        )
    return loaded


def _hit(row: _Row, score: float) -> Hit:
    return Hit(
        document=row.document,
        heading=row.heading,
        body=row.body,
        document_id=row.document_id,
        section_id=row.section_id,
        anchor=row.anchor,
        clause_id=row.clause_id,
        position=row.position,
        score=score,
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


def _query_terms(question: str, aliases: list[GlossaryAlias]) -> list[str]:
    terms = {term for term in (_index_term(token) for token in _TOKEN.findall(question)) if term}
    for alias in aliases:
        phrases = tuple(alias.phrases)
        if any(_phrase_in(phrase, question) for phrase in phrases):
            for phrase in phrases:
                terms.update(
                    term
                    for term in (_index_term(token) for token in _TOKEN.findall(phrase))
                    if term
                )
    return list(terms)


def _phrase_in(phrase: str, question: str) -> bool:
    parts = phrase.split()
    if not parts:
        return False
    body = r"\s+".join(re.escape(part) for part in parts)
    flags = 0 if phrase in CASE_SENSITIVE_ABBREVIATIONS else re.IGNORECASE
    return re.search(rf"(?<!\w){body}(?!\w)", question, flags) is not None


def _clause_terms(row: _Row) -> tuple[str, ...]:
    heading = [_index_term(token) for token in _TOKEN.findall(row.heading)]
    number = [_index_term(token) for token in _TOKEN.findall(row.clause_id)]
    document = [_index_term(token) for token in _TOKEN.findall(row.document)]
    body = [_index_term(token) for token in _TOKEN.findall(row.body)]
    return tuple(
        term for term in (*heading, *heading, *heading, *number, *number, *document, *body) if term
    )


def _index_term(token: str) -> str | None:
    if token in CASE_SENSITIVE_ABBREVIATIONS:
        return token
    folded = token.casefold()
    if folded in _STOPWORDS:
        return None
    if folded.isdigit():
        return folded if len(folded) >= 2 else None
    if _is_abbreviation(token):
        return folded
    if any("а" <= char <= "я" or char == "ё" for char in folded):
        stemmed = _stem(folded)
        if len(stemmed) < 4 or stemmed in _STOPWORDS:
            return None
        return stemmed
    if len(folded) < 3:
        return None
    return folded


def _is_abbreviation(token: str) -> bool:
    letters = [char for char in token if char.isalpha()]
    if not letters or len(token) > 12:
        return False
    if all(char.isupper() for char in letters):
        return True
    return any(char.isupper() for char in letters[1:])


def _stem(folded: str) -> str:
    for suffix in _SUFFIXES:
        if folded.endswith(suffix) and len(folded) - len(suffix) >= 4:
            folded = folded[: -len(suffix)]
            break
    if len(folded) > 6:
        return folded[:6]
    return folded


def _overlap_ok(query_terms: list[str], doc_terms: tuple[str, ...]) -> bool:
    unique = set(query_terms)
    if not unique:
        return False
    hits = len(unique & set(doc_terms))
    if len(unique) <= 2:
        return hits >= 1 and hits / len(unique) >= 0.5
    return hits >= 2 and hits / len(unique) >= 0.2


def _bm25(query_terms: list[str], docs: tuple[tuple[str, ...], ...]) -> list[float]:
    doc_count = len(docs)
    df: dict[str, int] = {}
    for doc in docs:
        for term in set(doc):
            df[term] = df.get(term, 0) + 1
    avgdl = sum(len(doc) for doc in docs) / doc_count
    scores: list[float] = []
    unique_query = set(query_terms)
    for doc in docs:
        tf: dict[str, int] = {}
        for term in doc:
            tf[term] = tf.get(term, 0) + 1
        doc_len = len(doc) or 1
        score = 0.0
        for term in unique_query:
            freq = tf.get(term, 0)
            if freq == 0:
                continue
            idf = math.log(1 + (doc_count - df[term] + 0.5) / (df[term] + 0.5))
            denom = freq + _BM25_K1 * (1 - _BM25_B + _BM25_B * doc_len / avgdl)
            score += idf * (freq * (_BM25_K1 + 1)) / denom
        scores.append(score)
    return scores
