# Knowledge catalog

`back/knowledge` owns the regulations. Chat does not read `data/knowlage_files` and does not keep a corpus in memory. The folder is still the source: on startup the service applies Alembic and upserts the markdown into Postgres schema `knowledge`, database `rag`.

A citation is `/kb/{document_id}#s-{section_id}`. Those ids are the primary keys.

| Id | Rule |
| --- | --- |
| `document_id` | File stem, or `glossary` |
| `section_id` | Leading number on the `##` line, `intro`, a slug, or a glossary abbreviation |
| `clause_id` | `1.1` inside a section, or the section id when the block has no numbered clause |
| `anchor` | `s-` plus `section_id` |

`glossary.md` is the glossary. Every other `*.md` file is a regulation. The `#` line is the title. Each `##` block is a section. Text before the first `##` is `Введение` (`section_id` `intro`). A duplicate `section_id` in one file, or a duplicate `clause_id` in one section, fails the load. A file is skipped when `content_sha256` already matches, unless any of its clauses has a null `lemma_text`.

## Schema

```sql
create schema if not exists knowledge;

create table knowledge.documents (
    id text primary key,
    kind text not null check (kind in ('regulation', 'glossary')),
    title text not null,
    source_name text not null,
    source_markdown text not null,
    content_sha256 text not null,
    loaded_at timestamptz not null default now()
);

create table knowledge.sections (
    document_id text not null references knowledge.documents (id) on delete cascade,
    section_id text not null,
    position integer not null check (position >= 0),
    heading text not null,
    anchor text not null,
    body_markdown text not null,
    primary key (document_id, section_id),
    unique (document_id, position)
);

create table knowledge.clauses (
    document_id text not null,
    section_id text not null,
    clause_id text not null,
    position integer not null check (position >= 0),
    body_markdown text not null,
    lemma_text text,
    search_vector tsvector not null,
    primary key (document_id, section_id, clause_id),
    unique (document_id, section_id, position),
    foreign key (document_id, section_id)
        references knowledge.sections (document_id, section_id)
        on delete cascade
);

create table knowledge.glossary_aliases (
    abbreviation text primary key,
    phrases text[] not null,
    case_sensitive boolean not null
);
```

Only regulation clauses are searched. The glossary is one document, `id = glossary`. Each abbreviation is a section. Alias lines (`abbreviation = phrase; phrase`, prefixes `то же:`, `должность:`, `документ:`, `вместе с` stripped) fill `glossary_aliases`. `case_sensitive` is true for `ПО`, `ТП`, `КП`, `ЗП`, `КИ`, and `СБ`.

`lemma_text` is the clause body as pymorphy3 lemmas, stopwords already removed. `search_vector` stores the lemmatized heading, clause number, and title. A GIN index also covers `to_tsvector('simple', coalesce(lemma_text, ''))`. Search does not read either of those; ranking is BM25 in the process.

## Search

`POST /search/clauses` lemmatizes the question, expands glossary aliases, and ranks every clause in scope with BM25 (`k1 = 1.5`, `b = 0.75`). The heading is counted three times, the clause number twice, the document title once, and the body once. `ПО`, `ТП`, `КП`, `ЗП`, `КИ`, and `СБ` match only in that case and are not lemmatized.

A hit stays when the best clause overlaps the query enough and the score is at least 20% of the best. At most 36 clauses are returned, within 48 000 characters. Neighbors of the top two hits in the same section are added and do not push a scored clause out. A dialogue that already knows the directorate passes `document_id`s, and those rows are the whole corpus for that score.

The same ranker backs MCP `search_sections`.

## HTTP and MCP

The service listens on `127.0.0.1:8001`. Chat proxies the reader routes, so the Vite app still calls `/api/documents` and `/api/glossary`.

| Call | Reads |
| --- | --- |
| `GET /documents` | titles and section headings |
| `GET /documents/{id}` | one document, section bodies |
| `GET /documents/{id}/sections/{section_id}` | one section |
| `GET /glossary` | the glossary file |
| `GET /prompt-context` | glossary text, regulation titles, headings, aliases |
| `POST /search/clauses` | ranked clauses |
| MCP `/mcp` | `list_documents`, `get_outline`, `get_section`, `get_document`, `search_sections`, `get_glossary` |

The chat turn uses `POST /search/clauses` and `GET /prompt-context`. It does not call the MCP tools. Cursor can.

## Code

| Piece | Place |
| --- | --- |
| Schema | `back/knowledge/alembic`, `knowledge/models.py` |
| Parse and upsert | `knowledge/parse.py`, `knowledge/load.py` |
| BM25 | `knowledge/search.py` |
| HTTP | `knowledge/routes.py` |
| MCP | `knowledge/tools.py` |
| Files | `data/knowlage_files/` |
