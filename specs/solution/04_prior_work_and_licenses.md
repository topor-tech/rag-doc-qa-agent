# Укажите свои наработки до спринта и сторонние компоненты, модели и API с лицензиями. Раскрытые наработки оценку не снижают.

До спринта готового агента не было. Репозиторий начат 26 ноября с одного README. Чат, поиск, каталог и интерфейс написаны 26–27 ноября. Четыре регламента и глоссарий даны организаторами, это не наша прежняя наработка. Чужой код поиска, LangChain и готовый RAG мы не подключали: разбор markdown, BM25 и проверка ссылок — свой код.

**Модель и API.** `deepseek-v4.1-flash`. Веса и репозиторий модели — MIT: [deepseek-ai/DeepSeek-V4.1-Flash](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash). В этом контуре веса не запускаются локально. Вызов идёт по платному OpenAI-совместимому API `https://ai.reg.cloud/v1`; к вызову применяются условия этого провайдера, а не лицензия весов. Эмбеддингов нет.

**Своя сборка опирается на такие компоненты:**

| Компонент | Лицензия |
| --- | --- |
| FastAPI, SQLAlchemy, Alembic, Pydantic, MCP SDK, React, Vite, react-markdown, remark-gfm | MIT |
| Клиент `openai` | Apache-2.0 |
| uvicorn, Starlette, httpx | BSD-3-Clause |
| psycopg | LGPL-3.0-only |
| PostgreSQL | PostgreSQL License |
| pymorphy3 (код) | MIT |
| Словарь pymorphy3-dicts-ru | данные OpenCorpora, CC BY-SA 3.0 |
