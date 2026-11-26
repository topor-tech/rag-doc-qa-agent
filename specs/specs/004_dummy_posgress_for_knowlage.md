# Postgres for the knowledge catalog

`back/chat/chat` keeps the regulations in one process-wide `Corpus`. `load_knowledge` reads `data/knowlage_files` at startup, and every search walks that object. Sessions stay in memory too; this slice does not move them.

The catalog moves into the Postgres 17 database already defined in `docker-compose.local.yml` (`rag` on port 5432). A separate knowledge service owns ingest and search. Chat asks that service over MCP and stops holding the files.

## Shape

```mermaid
flowchart TD
    files["data/knowlage_files/*.md"] --> loader[Loader on knowledge startup]
    loader --> db[("Postgres schema knowledge")]
    db --> svc[Knowledge service]
    svc --> mcp["MCP /mcp"]
    svc --> http["HTTP /documents and /glossary"]
    mcp --> chat[Chat: search, then answer]
    http --> chat
    chat --> ui[Vite app, still via /api]
```

Chat remains the only process that calls the model. It no longer imports the corpus. The reader routes and the MCP tools keep the names and payloads in `kb_http.py` and `kb_mcp.py`. Chat proxies `/documents` and `/glossary` so the front does not gain a second origin. Cursor and the chat turn both call the knowledge service at `/mcp`.

The public ids do not change. A citation is still `/kb/{document_id}#s-{section_id}`.

| Id | Still |
| --- | --- |
| `document_id` | File stem, or `glossary` |
| `section_id` | Leading number on the `##` line, `intro`, a slug, or a glossary abbreviation |
| `clause_id` | `1.1` inside a section, or the section id when the block has no numbered clause |
| `anchor` | `s-` plus `section_id` |

## Why a separate service

Search and the reader use the same rows. Putting them in the knowledge service means chat does not load the folder, and the model tools cannot drift from the HTTP catalog. One database is enough. The service is stateless apart from its connection pool: the index lives in Postgres, not in a second copy of `Corpus`.

In-process BM25 stays out of this slice. Ranking becomes `ts_rank_cd` over a `tsvector` built with the `russian` configuration. Scores will not match the current stemmer. The caps stay: at most 8 clauses, a hit must reach 40% of the best score, bodies stay within 18 000 characters, and the clause before and after a top hit in the same section is still included. A dialogue that already knows the directorate passes `document_id`s into the query.

Glossary expansion stays in the service, before the tsquery is built. Alias lines are rows, not a scan of the glossary string on every question.

## Schema `knowledge`

Surrogate uuids are not used for regulations. The primary keys are the ids the reader and the answers already cite.

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
    search_vector tsvector not null,
    primary key (document_id, section_id, clause_id),
    unique (document_id, section_id, position),
    foreign key (document_id, section_id)
        references knowledge.sections (document_id, section_id)
        on delete cascade
);

create index clauses_search_idx
    on knowledge.clauses
    using gin (search_vector);

create table knowledge.glossary_aliases (
    abbreviation text primary key,
    phrases text[] not null,
    case_sensitive boolean not null
);
```

`documents.source_markdown` is the file as loaded. `content_sha256` is the hash of those bytes. Regulation HTTP `get_document` is still assembled from sections. `get_glossary` without a term returns the glossary file from `source_markdown`.

The glossary is one `documents` row, `id = glossary`, `kind = glossary`. Each abbreviation is a section. Glossary text is not copied into `clauses`. Only regulation clauses are searched. Aliases are loaded from the same lines the parser already understands (`abbreviation = phrase; phrase`, prefixes `то же:`, `должность:`, `документ:`, `вместе с` stripped). `case_sensitive` is true for `ПО`, `ТП`, `КП`, `ЗП`, `КИ`, and `СБ`.

`clauses.search_vector` is written by the loader, not by a trigger. Weights:

| Piece | Weight |
| --- | --- |
| Section heading | A |
| Clause number | A |
| Document title | B |
| Clause body | C |

`position` on `clauses` is the order inside the section. Neighbor lookup is `position` between the hit and one step either side, same `document_id` and `section_id`. `position` on `sections` is the outline order.

A duplicate `section_id` in one file, or a duplicate `clause_id` in one section, fails the load. That matches today's section check and closes the same hole for clauses.

## Load

The folder remains the source. On startup the knowledge service parses with the same rules as `knowledge.py` and upserts one document per file inside a transaction:

1. Skip the file when `content_sha256` already matches.
2. Otherwise replace that document's sections and clauses (`delete` cascades) and insert the new rows and aliases.
3. Refuse to serve if the glossary file or the regulation set is missing, as startup does now.

Chat does not read `KNOWLEDGE_DIR`. The knowledge service does.

## Search

`search_clauses` in the service:

```sql
select document_id, section_id, clause_id,
       ts_rank_cd(search_vector, q) as score
from knowledge.clauses,
     websearch_to_tsquery('russian', :query) q
where search_vector @@ q
  and (:document_ids::text[] is null or document_id = any(:document_ids))
order by score desc
limit 30;
```

`:query` is the user question after alias expansion. The service then applies the 40% floor, the character budget, and the neighbor rows, and returns at most 8 clauses. `search_sections` groups those clauses by `(document_id, section_id)` and attaches the section heading, the best score, a short snippet, and `path`.

Outline, one section, one document, and one glossary term are primary-key reads. They do not use the index.

## What chat calls

The tool names stay.

| Call from chat | Reads |
| --- | --- |
| `search_sections` / clause search for the turn | `clauses` ranked, then `sections` |
| `get_section` | one `sections` row |
| `get_outline`, `list_documents` | `documents` and section headings |
| `get_document` | sections, or `source_markdown` for the glossary |
| `get_glossary` | `documents` plus `glossary_aliases` or one section |

The preselected-context path in `llm.py` uses the same search call as the MCP tool. It does not keep a private ranker.

## Place in the repo

| Piece | Place |
| --- | --- |
| Schema | applied by the knowledge service on startup against `DATABASE_URL` |
| Parse and upsert | `back/knowledge`, reusing the current split into sections and clauses |
| MCP and HTTP | that service, port `8001` |
| Proxy and model call | `back/chat` |
| Files | `data/knowlage_files/` |
| Database | service `postgres` in `docker-compose.local.yml`, database `rag`, schema `knowledge` |

`DATABASE_URL` for local compose is `postgresql://postgres:postgres@localhost:5432/rag`.

## Out of this slice

- Chat sessions, dialogue state, and the clarification counter. They stay in the chat process.
- Expert answers. When they arrive they get their own table, with a link to the question and the `document_id`s they apply to. They are not rows in `clauses`. A regulation and a confirmed clarification must stay distinguishable.
- Embeddings. A later slice can add a vector column on `clauses` and a second rank step. It does not need a new database.
- Uploads, Confluence, and accounts. The folder remains the source.
- Copying the hand-rolled stemmer into SQL. Russian full text replaces it.
