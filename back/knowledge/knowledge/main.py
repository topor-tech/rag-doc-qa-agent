"""Apply Alembic revisions, then serve the catalog."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from alembic.config import Config
from fastapi import FastAPI

from alembic import command
from knowledge.db import database_url
from knowledge.load import load_knowledge
from knowledge.routes import router
from knowledge.tools import http_app as mcp_http

logger = logging.getLogger(__name__)


def upgrade() -> None:
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url())
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    upgrade()
    load_knowledge()
    async with mcp_http.router.lifespan_context(mcp_http):
        yield


app = FastAPI(title="Knowledge", lifespan=lifespan)
app.include_router(router)
app.router.routes.extend(mcp_http.routes)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logger.info("knowledge service listening on http://127.0.0.1:8001")
    uvicorn.run(app, host="127.0.0.1", port=8001)


if __name__ == "__main__":
    main()
