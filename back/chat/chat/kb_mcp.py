"""MCP tools for the same catalog the HTTP API serves.

Run a stdio server for a local agent with `python -m chat.kb_mcp`.
The FastAPI app mounts the Streamable HTTP endpoint at `/mcp`.
"""

from mcp.server.mcpserver import MCPServer

from chat.knowledge import (
    document_markdown,
    find_document,
    find_glossary_term,
    find_section,
    get_corpus,
    load_knowledge,
    section_snippet,
)
from chat.knowledge import (
    search_sections as rank_sections,
)

mcp = MCPServer(
    name="knowledge-base",
    instructions=(
        "Корпоративные регламенты и глоссарий. "
        "Сначала search_sections, затем get_section для каждого раздела, на который ссылаешься. "
        "В ответе пользователю вставляй markdown-ссылку path без изменений. "
        "Ссылка на документ целиком берётся из path документа, например [Пресейловая деятельность Дирекции ИБ](/kb/presales-activity-ib). "
        "Текст такой ссылки — название документа. "
        "Ссылка на раздел берётся из path раздела, текст ссылки — заголовок раздела. "
        "get_document читай только когда нужен документ целиком."
    ),
)


@mcp.tool()
def list_documents() -> list[dict[str, str | int]]:
    """Список регламентов и глоссария: id, название, ссылка path и число разделов, без текста."""
    corpus = get_corpus()
    documents = (*corpus.documents, corpus.glossary_document)
    return [
        {
            "id": document.id,
            "title": document.title,
            "path": document.path,
            "section_count": len(document.sections),
        }
        for document in documents
    ]


@mcp.tool()
def get_outline(document_id: str) -> dict[str, object]:
    """Оглавление документа: заголовки, id разделов и ссылки, без текста разделов."""
    document = find_document(document_id)
    if document is None:
        raise ValueError(f"document not found: {document_id}")
    return {
        "document_id": document.id,
        "title": document.title,
        "path": document.path,
        "sections": [
            {
                "section_id": section.section_id,
                "heading": section.heading,
                "anchor": section.anchor,
                "path": section.path,
            }
            for section in document.sections
        ],
    }


@mcp.tool()
def get_section(document_id: str, section_id: str) -> dict[str, str]:
    """Текст одного раздела и ссылка path, которой цитирует ответ."""
    section = find_section(document_id, section_id)
    if section is None:
        raise ValueError(f"section not found: {document_id}/{section_id}")
    return {
        "document_id": section.document_id,
        "document_title": section.document,
        "document_path": f"/kb/{section.document_id}",
        "section_id": section.section_id,
        "heading": section.heading,
        "anchor": section.anchor,
        "path": section.path,
        "body_markdown": section.body,
    }


@mcp.tool()
def get_document(document_id: str) -> dict[str, str]:
    """Полный markdown документа. Для одного раздела используй get_section."""
    document = find_document(document_id)
    if document is None:
        raise ValueError(f"document not found: {document_id}")
    return {
        "document_id": document.id,
        "title": document.title,
        "path": document.path,
        "markdown": document_markdown(document),
    }


@mcp.tool(name="search_sections")
def search_sections(query: str) -> list[dict[str, str | float]]:
    """Найти разделы регламентов по вопросу. Тот же отбор, что и у чата."""
    return [
        {
            "document_id": section.document_id,
            "document_title": section.document,
            "document_path": f"/kb/{section.document_id}",
            "section_id": section.section_id,
            "heading": section.heading,
            "score": score,
            "snippet": section_snippet(section.body),
            "path": section.path,
        }
        for section, score in rank_sections(query)
    ]


@mcp.tool()
def get_glossary(term: str = "") -> dict[str, str]:
    """Глоссарий целиком, либо один термин, если передан term."""
    if term.strip():
        section = find_glossary_term(term)
        if section is None:
            raise ValueError(f"glossary term not found: {term}")
        return {
            "document_id": section.document_id,
            "document_title": section.document,
            "document_path": f"/kb/{section.document_id}",
            "section_id": section.section_id,
            "heading": section.heading,
            "path": section.path,
            "body_markdown": section.body,
        }
    corpus = get_corpus()
    return {
        "document_id": corpus.glossary_document.id,
        "document_title": corpus.glossary_document.title,
        "path": corpus.glossary_document.path,
        "text": corpus.glossary.strip(),
    }


http_app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    json_response=True,
    stateless_http=True,
)


def main() -> None:
    load_knowledge()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
