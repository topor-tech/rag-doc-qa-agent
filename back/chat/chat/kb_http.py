"""Proxy the reader routes to the knowledge service."""

from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from chat.knowledge import knowledge_url

router = APIRouter()


def _proxy(path: str) -> Response:
    try:
        upstream = httpx.get(f"{knowledge_url()}{path}", timeout=30)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="База знаний недоступна") from exc
    media_type = upstream.headers.get("content-type", "application/json")
    return Response(
        content=upstream.content, status_code=upstream.status_code, media_type=media_type
    )


@router.get("/documents")
def list_documents() -> Response:
    return _proxy("/documents")


@router.get("/documents/{document_id}")
def read_document(document_id: str) -> Response:
    return _proxy(f"/documents/{quote(document_id, safe='')}")


@router.get("/documents/{document_id}/sections/{section_id}")
def read_section(document_id: str, section_id: str) -> Response:
    document = quote(document_id, safe="")
    section = quote(section_id, safe="")
    return _proxy(f"/documents/{document}/sections/{section}")


@router.get("/glossary")
def read_glossary() -> Response:
    return _proxy("/glossary")
