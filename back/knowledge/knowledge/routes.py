"""Read-only HTTP catalog. Chat proxies these routes to the Vite app."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from knowledge.catalog import (
    DocumentView,
    SectionView,
    find_document,
    find_section,
    list_regulations,
    prompt_context,
)
from knowledge.db import session_scope
from knowledge.parse import GLOSSARY_ID
from knowledge.search import search_clauses

router = APIRouter()


class SectionOutline(BaseModel):
    id: str
    heading: str
    anchor: str


class DocumentOutline(BaseModel):
    id: str
    title: str
    source_name: str
    sections: list[SectionOutline]


class DocumentList(BaseModel):
    documents: list[DocumentOutline]


class SectionBody(BaseModel):
    id: str
    anchor: str
    heading: str
    body_markdown: str
    path: str


class DocumentDetail(BaseModel):
    id: str
    title: str
    source_name: str
    sections: list[SectionBody]


class SectionDetail(SectionBody):
    document_id: str
    document_title: str


class SearchIn(BaseModel):
    query: str
    document_ids: list[str] | None = None


class ClauseOut(BaseModel):
    document: str
    heading: str
    body: str
    document_id: str
    section_id: str
    anchor: str
    clause_id: str
    path: str
    score: float


class SearchOut(BaseModel):
    clauses: list[ClauseOut]


class PromptDocumentOut(BaseModel):
    id: str
    title: str
    path: str


class PromptOut(BaseModel):
    glossary: str
    regulations: list[PromptDocumentOut]
    catalog: list[PromptDocumentOut]
    headings: list[str]
    aliases: str


def get_session() -> Iterator[Session]:
    with session_scope() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def _outline(document: DocumentView) -> DocumentOutline:
    return DocumentOutline(
        id=document.id,
        title=document.title,
        source_name=document.source_name,
        sections=[
            SectionOutline(id=section.section_id, heading=section.heading, anchor=section.anchor)
            for section in document.sections
        ],
    )


def _detail(document: DocumentView) -> DocumentDetail:
    return DocumentDetail(
        id=document.id,
        title=document.title,
        source_name=document.source_name,
        sections=[
            SectionBody(
                id=section.section_id,
                anchor=section.anchor,
                heading=section.heading,
                body_markdown=section.body,
                path=section.path,
            )
            for section in document.sections
        ],
    )


@router.get("/documents", response_model=DocumentList)
def read_documents(session: SessionDep) -> DocumentList:
    return DocumentList(documents=[_outline(document) for document in list_regulations(session)])


@router.get("/documents/{document_id}", response_model=DocumentDetail)
def read_document(document_id: str, session: SessionDep) -> DocumentDetail:
    document = find_document(session, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Документ не найден")
    return _detail(document)


@router.get("/documents/{document_id}/sections/{section_id}", response_model=SectionDetail)
def read_section(
    document_id: str,
    section_id: str,
    session: SessionDep,
) -> SectionDetail:
    section = find_section(session, document_id, section_id)
    if section is None:
        raise HTTPException(status_code=404, detail="Раздел не найден")
    return _section_detail(section)


@router.get("/glossary", response_model=DocumentDetail)
def read_glossary(session: SessionDep) -> DocumentDetail:
    document = find_document(session, GLOSSARY_ID)
    if document is None:
        raise HTTPException(status_code=404, detail="Документ не найден")
    return _detail(document)


@router.get("/prompt-context", response_model=PromptOut)
def read_prompt_context(session: SessionDep) -> PromptOut:
    context = prompt_context(session)
    return PromptOut(
        glossary=context.glossary,
        regulations=[
            PromptDocumentOut(id=item.id, title=item.title, path=item.path)
            for item in context.regulations
        ],
        catalog=[
            PromptDocumentOut(id=item.id, title=item.title, path=item.path)
            for item in context.catalog
        ],
        headings=list(context.headings),
        aliases=context.aliases,
    )


@router.post("/search/clauses", response_model=SearchOut)
def read_search(body: SearchIn, session: SessionDep) -> SearchOut:
    hits = search_clauses(session, body.query, body.document_ids)
    return SearchOut(
        clauses=[
            ClauseOut(
                document=hit.document,
                heading=hit.heading,
                body=hit.body,
                document_id=hit.document_id,
                section_id=hit.section_id,
                anchor=hit.anchor,
                clause_id=hit.clause_id,
                path=hit.path,
                score=hit.score,
            )
            for hit in hits
        ]
    )


def _section_detail(section: SectionView) -> SectionDetail:
    return SectionDetail(
        id=section.section_id,
        anchor=section.anchor,
        heading=section.heading,
        body_markdown=section.body,
        path=section.path,
        document_id=section.document_id,
        document_title=section.document_title,
    )
