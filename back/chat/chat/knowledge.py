"""Calls the knowledge service. This process does not keep the catalog."""

import os
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel

DEFAULT_URL = "http://127.0.0.1:8001"
MAX_CLARIFICATIONS = 3


class KnowledgeUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class Clause:
    document: str
    heading: str
    body: str
    document_id: str
    section_id: str
    anchor: str
    clause_id: str

    @property
    def path(self) -> str:
        return f"/kb/{self.document_id}#{self.anchor}"


@dataclass(frozen=True)
class CatalogDocument:
    id: str
    title: str
    path: str


@dataclass(frozen=True)
class PromptContext:
    glossary: str
    regulations: tuple[CatalogDocument, ...]
    catalog: tuple[CatalogDocument, ...]
    headings: tuple[str, ...]
    aliases: str


class _CatalogItem(BaseModel):
    id: str
    title: str
    path: str


class _ClauseItem(BaseModel):
    document: str
    heading: str
    body: str
    document_id: str
    section_id: str
    anchor: str
    clause_id: str
    score: float


class _PromptBody(BaseModel):
    glossary: str
    regulations: list[_CatalogItem]
    catalog: list[_CatalogItem]
    headings: list[str]
    aliases: str


class _SearchBody(BaseModel):
    clauses: list[_ClauseItem]


_context: PromptContext | None = None


def knowledge_url() -> str:
    return os.environ.get("KNOWLEDGE_URL", DEFAULT_URL).rstrip("/")


def prompt_context() -> PromptContext:
    global _context
    if _context is None:
        _context = _fetch_prompt()
    return _context


def search_clauses(
    question: str,
    document_ids: frozenset[str] | None = None,
) -> list[tuple[Clause, float]]:
    payload = {
        "query": question,
        "document_ids": None if document_ids is None else sorted(document_ids),
    }
    body = _SearchBody.model_validate(_json("POST", "/search/clauses", payload))
    return [
        (
            Clause(
                document=item.document,
                heading=item.heading,
                body=item.body,
                document_id=item.document_id,
                section_id=item.section_id,
                anchor=item.anchor,
                clause_id=item.clause_id,
            ),
            item.score,
        )
        for item in body.clauses
    ]


def _fetch_prompt() -> PromptContext:
    body = _PromptBody.model_validate(_json("GET", "/prompt-context", None))
    return PromptContext(
        glossary=body.glossary,
        regulations=tuple(_document(item) for item in body.regulations),
        catalog=tuple(_document(item) for item in body.catalog),
        headings=tuple(body.headings),
        aliases=body.aliases,
    )


def _document(item: _CatalogItem) -> CatalogDocument:
    return CatalogDocument(id=item.id, title=item.title, path=item.path)


def _json(method: str, path: str, payload: dict[str, Any] | None) -> Any:
    try:
        response = httpx.request(method, f"{knowledge_url()}{path}", json=payload, timeout=30)
    except httpx.HTTPError as exc:
        raise KnowledgeUnavailableError("knowledge service is unavailable") from exc
    if response.status_code >= 400:
        raise KnowledgeUnavailableError(
            f"knowledge service returned {response.status_code} for {path}"
        )
    return response.json()
