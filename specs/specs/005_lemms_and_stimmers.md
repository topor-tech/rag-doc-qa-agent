# Lemmas instead of the short stemmer

The question «Расчёт сделан полгода назад, ставки ещё действуют. Можно просто использовать его?» should be answered from `presales-activity-ib` clauses 8.2–8.3. The chat answered from 13.13: no refresh is required while the cost rates are still in force, and the only thing left to check is whether the calculation's own validity has expired. That is what 13.13 says. It is the wrong rule for a calculation that is six months old.

## What the search returned

Two different queries were scored against the same catalog.

The raw question, before `pymorphy3`, kept clause 8.3 only as a neighbor of 8.4. The best hit was a ДБРЦТ clause. 13.13 was not in that shortlist.

The chat does not search the raw question alone. `rewrite_query` in `back/chat/chat/llm.py` asks the model for one line of regulation terms and appends that line to the question. For this question the line was «Проверка и актуализация расчетов Расчет проекта» — the heading of section 13, plus a fragment of the heading of section 8. Headings are indexed three times, so every clause in section 13 outscored section 8. 13.13 scored about 20. The 40% floor was about 8, and 8.2–8.4 (about 7) fell off. The model then applied the only refresh rule it could see.

A later turn pasted the expected answer and the numbers 8.2–8.3. Those words are the text of 8.3, so 8.3 ranked first (about 41) and the model corrected itself.

## Why the raw question barely matched 8.3

The stemmer in `back/knowledge/knowledge/search.py` stripped one suffix and then cut the token to six characters. Three pairs that matter for this question did not meet.

| Question | Clause 8.3 | Short stemmer |
| --- | --- | --- |
| расчёт | расчет, расчета | `расчёт` and `расчет` stayed different. `ё` was not folded to `е`. |
| ставки | ставок | `ставки` became `ставк`. `ставок` has a fleeting `о` and matched no suffix, so it stayed `ставок`. `ставках` did become `ставк`, which is why 8.4 (it says «ставках») ranked and 8.3 only rode in as its neighbor. |
| полгода | 6 месяцев | `полгод` and `месяц`. Different words, not different forms. |

`действуют` and `действия` both became `действ`, so that pair matched by accident.

## Libraries tried on the same pairs

| Library | расчёт / расчет | ставки / ставок | What else |
| --- | --- | --- | --- |
| Short stemmer in the service | different | different | Cuts every token to six characters, so `заказчик` and `заказчиком` both became `заказч`. |
| `snowballstemmer` (the Russian Snowball stemmer NLTK wraps) | both `расчет` | still `ставк` / `ставок` | Folds `ё`. Does not fix the fleeting vowel. |
| `simplemma` | `расчёт` → `расчет`, but `расчёта` stayed `расчёта` | both `ставка` | `ё` handling is inconsistent. `трудозатрат` was left as is. |
| `pymorphy3` | both `расчёт` | `ставки`, `ставок`, `ставках`, `ставка` all → `ставка` | Also `заявок`/`заявки` → `заявка`, `истек`/`истёк` → `истечь`. |

`pymorphy3` is a lemmatizer: it writes the dictionary form, it does not chop a suffix. The package code is MIT. The Russian dictionary it ships is OpenCorpora data under CC BY-SA 3.0; the catalog should name that source. It runs on the project's Python 3.14.

A lemma keeps part of speech. `действуют` becomes `действовать` and `действия` becomes `действие`, so the accidental overlap from the six-character stem is gone. `полгода` stays `полгода`. The first analysis wins when a form is ambiguous: `данные` can be read as a form of `дать`.

## What changed

`_stem` and the six-character cut are gone. A Russian token is indexed as `MorphAnalyzer.parse(word)[0].normal_form`. One analyzer is created per process, and lemmas are cached. Stopwords are still dropped, including when the lemma itself is a stopword. `ПО`, `ТП`, `КП`, `ЗП`, `КИ`, and `СБ` are still matched only in that case and are not lemmatized.

The original clause text stays in `clauses.body_markdown`. Alembic revision `0002_clause_lemmas` adds nullable `clauses.lemma_text`. On load, that column receives the body lemmas joined by spaces, in token order, with stopwords already removed. A file whose hash has not changed is loaded again while any of its clauses has a null `lemma_text`.

Ranking is BM25 (`k1 = 1.5`, `b = 0.75`) over those lemmas, in the service, across every clause in scope. The query is lemmatized at search time. The body bag is the stored `lemma_text`. The heading is counted three times, the clause number twice, and the document title once; those three are lemmatized when the query runs. A null `lemma_text` falls back to lemmatizing `body_markdown`. A hit stays when its score is at least 20% of the best. At most 36 clauses are returned, within 48 000 characters. Neighbors of the top two hits are added and do not push a scored clause out. The chat tells the model that this list is lexical candidates and that it should cite only the clauses that fit the question. Revision `0003_lemma_text_index` still adds a GIN index on `to_tsvector('simple', coalesce(lemma_text, ''))`, and `search_vector` still stores the lemmatized heading, clause number, and title. The ranker does not read them.

For clause 8.3 the stored line contains `расчёт`, `месяц`, and `ставка`.

## Still open

The rewrite is unchanged. A line that copies the heading «Проверка и актуализация расчетов» can still lift section 13, because the heading is counted three times in the BM25 bag. `полгода` and `6 месяцев` are still different terms. A dense embedding over the same clause rows would connect those paraphrases; `pgvector` on this Postgres is enough, and the two lists should be fused so one strong heading match cannot raise the floor for the other.
