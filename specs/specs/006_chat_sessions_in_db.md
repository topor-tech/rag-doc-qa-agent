# Chat sessions in Postgres

A session id is already a UUID. `SessionStore.create` in `back/chat/chat/sessions.py` sets `id` to `uuid4()`, and `POST /sessions` returns it. The store is a process dict. A restart drops every dialogue, and the page keeps the id only in a ref, so a reload starts empty.

This slice writes that id into Postgres and reads it back. An anonymous user is a row created with a cookie. That user sees their own dialogues, and F5 on `/c/{uuid}` loads that dialogue again. Someone who opens the same link gets the transcript and cannot send. Each exchange also leaves a debug row: the search text, the rewrite, the shortlist, and whether the reply was cleaned.

Regulations stay in schema `knowledge`. Dialogues get schema `chat` in the same database `rag`. This replaces the line in `004_dummy_posgress_for_knowlage.md` that left sessions in the chat process.

## Shape

```mermaid
flowchart TD
    browser["Browser, cookie chat_visitor"] --> page["Page /c/uuid"]
    page --> list["GET /sessions"]
    page --> read["GET /sessions/id"]
    page --> send["POST /sessions/id/messages"]
    list --> db[("Postgres schema chat")]
    read --> db
    send --> db
    send --> model[Model]
    send --> kb[Knowledge search]
```

The dialogue id in the URL is `chat.sessions.id`. The cookie names the owner. The two are different values.

| Who opens `/c/{uuid}` | Transcript | Composer |
| --- | --- | --- |
| The visitor who created it | yes | on |
| Any other visitor | yes | off |

The other visitor's list does not gain this dialogue. Reading it does not change `owner_id`.

## Anonymous user

The first request that arrives without a valid `chat_visitor` cookie inserts `chat.visitors` and sets the cookie. A later request hashes the cookie and loads that row.

The cookie value is `secrets.token_urlsafe(32)`. The table stores `sha256` of that string as hex in `token_hash`. The raw token is not stored and not logged. A cookie whose hash matches no row is treated as absent, and a new visitor is issued.

Attributes: `HttpOnly`, `SameSite=Lax`, `Path=/`, `Max-Age` 400 days. `Secure` is set when the request is HTTPS. Local Vite is plain HTTP, so the cookie is still stored there. The browser talks to the Vite origin, and Vite proxies `/api` to the chat process, so the cookie belongs to that origin and goes out with each `/api` call.

Clearing the cookie starts a new visitor. The old rows stay with the old visitor. This browser can still open an old `/c/{uuid}` and read it, and the composer stays off.

## Schema `chat`

```sql
create schema if not exists chat;

create table chat.visitors (
    id uuid primary key default uuidv7(),
    token_hash text not null unique,
    created_at timestamptz not null default now()
);

create table chat.sessions (
    id uuid primary key default uuidv7(),
    owner_id uuid not null references chat.visitors (id) on delete cascade,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    title text check (title is null or char_length(title) between 1 and 80)
);

create index sessions_owner_updated_idx
    on chat.sessions (owner_id, updated_at desc);

create table chat.messages (
    id uuid primary key default uuidv7(),
    session_id uuid not null references chat.sessions (id) on delete cascade,
    position integer not null check (position >= 0),
    role text not null check (role in ('user', 'assistant')),
    content text not null check (char_length(content) > 0),
    created_at timestamptz not null default now(),
    unique (session_id, position)
);

create table chat.turn_logs (
    id uuid primary key default uuidv7(),
    session_id uuid not null references chat.sessions (id) on delete cascade,
    position integer not null check (position >= 0),
    user_message_id uuid not null references chat.messages (id) on delete cascade,
    assistant_message_id uuid references chat.messages (id) on delete cascade,
    created_at timestamptz not null default now(),
    format_version integer not null check (format_version >= 1),
    payload jsonb not null,
    unique (session_id, position)
);
```

Every id in this schema is a UUID version 7. Postgres 18 fills it with `uuidv7()` as the column default. The chat process inserts the row and reads the id back. The local database is the `postgres:18` image in `docker-comose.local.yml`. The volume is mounted at `/var/lib/postgresql`, which is where that image keeps its data. A directory written by Postgres 17 does not start under 18; the volume is created empty and the knowledge service loads the catalog again on startup.

A version 7 id carries the generation time in its first 48 bits, so new rows land at the end of the primary-key index. The other bits are random. `/c/{uuid}` therefore shows when the dialogue was created, and one link does not identify another dialogue. `messages.position` and `created_at` stay the transcript order. `owner_id` is the visitor resolved from the cookie on `POST /sessions`.

`messages.position` is the transcript order, starting at 0. The next model call sends these rows in that order and ignores `turn_logs`. System text is rebuilt every turn from the catalog, so it is not a message.

`sessions.title` is the list label. It is filled from the first user message: one line, trimmed, cut at 80 characters. Until that message the title is null, and the list shows «Новый диалог». `updated_at` moves forward on every committed message. The list is `owner_id` plus `updated_at` descending, which is `sessions_owner_updated_idx`.

`turn_logs` is one row per exchange, in the same order as the user messages. The columns locate the exchange: which session, which position, which user message, and, when the model answered, which assistant message. A failed turn leaves `assistant_message_id` null. Everything that describes how the reply was made sits in `payload`. The next model call still reads `messages` and ignores `turn_logs`.

`format_version` says which shape `payload` has. This slice writes version 1 and does not rewrite a row when a later version appears. A reader branches on `format_version`. Old logs stay in the shape they were written in.

Version 1 is this object. `search_text` is `Dialogue.search_text()`. `rewritten_query` is the one line from `rewrite_query`, or null when that line is empty. `directorate_id` and `clarification_count` are what `read_dialogue` computed for this exchange. `retried` is true when the server asked the model a second time. `dropped_links` lists the `/kb/` targets removed by `drop_bad_links`. `draft_reply` is the model text from before that cleanup when it differs from the saved assistant message, and null otherwise. `error` is set only when `assistant_message_id` is null, to the text the API returned (`База знаний недоступна`, `Не удалось получить ответ модели`, or `Модель вернула пустой ответ`). `hits` is the shortlist in rank order, best first. A hit stores the ids and the score search returned. It does not copy the clause body, and it does not reference `knowledge.clauses`. The path is `/kb/{document_id}#s-{section_id}`.

```json
{
  "model": "deepseek-v4.1-flash",
  "temperature": 0.2,
  "search_text": "…",
  "rewritten_query": null,
  "directorate_id": null,
  "clarification_count": 0,
  "retried": false,
  "dropped_links": [],
  "draft_reply": null,
  "error": null,
  "hits": [
    {
      "document_id": "presales-activity-ib",
      "section_id": "8",
      "clause_id": "8.3",
      "score": 20.1
    }
  ]
}
```

## Access

| Call | Owner | Other visitor |
| --- | --- | --- |
| `GET /sessions` | that visitor's rows | that visitor's own rows |
| `POST /sessions` | inserts a row they own | inserts a row they own |
| `GET /sessions/{id}` | transcript, `writable: true` | transcript, `writable: false` |
| `POST /sessions/{id}/messages` | appends | 403, `Этот диалог только для чтения` |
| `GET /sessions/{id}/turn-logs` | the debug log | 403 |

A path that is not a UUID, or an id with no row, is 404 `Сессия не найдена` for every visitor. Write checks the row first, then `owner_id`.

`GET /sessions/{id}` returns `{id, title, writable, messages}`. Each message is `{id, role, content}` in `position` order. `GET /sessions` returns `{sessions: [{id, title, updated_at}]}` for the cookie's visitor.

The debug route is how the log is read. The chat page does not call it, and a shared link does not include it.

## Write path

`POST /sessions` inserts one `sessions` row with `owner_id` set from the cookie and returns it with an empty message list and `writable: true`.

`POST /sessions/{id}/messages` refuses a visitor who is not the owner. For the owner it does three steps. The model call sits between two transactions, so a row lock is not held while the model runs.

1. Lock the session row (`select … for update`). Insert the user message at `max(position) + 1`. On the first user message, set `title`. Set `updated_at`. Commit.
2. Build the history from `messages` and call `answer_turn`.
3. On success, lock the session again, insert the assistant message, insert the `turn_logs` row with `format_version` 1, set `updated_at`, commit. On failure, insert a `turn_logs` row with `assistant_message_id` null and `error` inside `payload`, and return the same 502 as today. The user message stays.

Two requests cannot take the same `position`. The in-memory dict and its locks go away. Postgres is the store, including across chat processes.

`chat.etalon_integration.ask` creates a session and then posts a message. It keeps the `Set-Cookie` from the create and sends that cookie on the post. A second call with no cookie is a new visitor and receives 403.

## Page

`/` is the chat screen with this visitor's list and no dialogue open. «Новый диалог» calls `POST /sessions` and moves to `/c/{uuid}`. Choosing a row does the same move. `App.jsx` treats `/c/{uuid}` as the chat route and passes the id in.

On `/c/{uuid}` the page calls `GET /sessions/{id}` and paints `messages`, using the server message id as the bubble key. F5 repeats that load because the id is in the path and the cookie is still sent. `writable: false` leaves the composer off. Links inside the transcript still open `/kb/…`. A 404 clears the open dialogue.

A failed exchange restores as a user bubble with no assistant bubble. The error text is on the turn, not in the transcript.

## Place in the repo

| Piece | Place |
| --- | --- |
| Schema | Alembic in `back/chat`, revision `0001_chat`, version table `chat.alembic_version`. Applied on chat startup against `DATABASE_URL` |
| Cookie and rows | `back/chat`. Replaces `SessionStore` |
| Routes | `back/chat/chat/main.py`, plus `GET /sessions` and `GET /sessions/{id}/turn-logs` |
| Address | `front/src/App.jsx` route `/c/{uuid}`, list and restore in `front/src/Chat.jsx` |
| Scenario runner | `back/chat/chat/etalon_integration.py` stores the visitor cookie between the two posts |
| Database | Same Postgres as the catalog, database `rag`, schema `chat` |

`DATABASE_URL` matches the knowledge service. Locally that is `postgresql://postgres:postgres@localhost:5432/rag`. The chat version table lives in schema `chat`, so these revisions do not share `public.alembic_version` with the knowledge service.

## Out of this slice

- Named accounts, login, and merging two cookies into one user.
- A copy of the clause body inside `hits`. The log keeps ids and scores. The text the model saw is the catalog row at that time.
- The full system prompt. It repeats the glossary and the clause bodies on every turn.
- Editing, deleting, or branching a dialogue. A shared link does not become a second copy.
- Expert answers and mail. Those stay a separate store, as in `004_dummy_posgress_for_knowlage.md`.
