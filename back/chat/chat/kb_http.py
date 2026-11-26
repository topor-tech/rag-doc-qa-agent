"""Read-only HTTP views of the knowledge catalog."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from chat.knowledge import Document, find_document, find_section, get_corpus

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


def _outline(document: Document) -> DocumentOutline:
    return DocumentOutline(
        id=document.id,
        title=document.title,
        source_name=document.source_name,
        sections=[
            SectionOutline(id=section.section_id, heading=section.heading, anchor=section.anchor)
            for section in document.sections
        ],
    )


def _detail(document: Document) -> DocumentDetail:
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
def list_documents() -> DocumentList:
    corpus = get_corpus()
    return DocumentList(documents=[_outline(document) for document in corpus.documents])


@router.get("/documents/{document_id}", response_model=DocumentDetail)
def read_document(document_id: str) -> DocumentDetail:
    document = find_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Документ не найден")
    return _detail(document)


@router.get("/documents/{document_id}/sections/{section_id}", response_model=SectionDetail)
def read_section(document_id: str, section_id: str) -> SectionDetail:
    section = find_section(document_id, section_id)
    if section is None:
        raise HTTPException(status_code=404, detail="Раздел не найден")
    return SectionDetail(
        id=section.section_id,
        anchor=section.anchor,
        heading=section.heading,
        body_markdown=section.body,
        path=section.path,
        document_id=section.document_id,
        document_title=section.document,
    )


@router.get("/glossary", response_model=DocumentDetail)
def read_glossary() -> DocumentDetail:
    return _detail(get_corpus().glossary_document)
