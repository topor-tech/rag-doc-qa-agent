"""Engine and sessions for the knowledge schema."""

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/rag"

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def database_url() -> str:
    raw = os.environ.get("DATABASE_URL", DEFAULT_URL).strip()
    if raw.startswith("postgresql://"):
        return "postgresql+psycopg://" + raw.removeprefix("postgresql://")
    return raw


def get_engine() -> Engine:
    global _engine, _session_factory
    if _engine is None:
        _engine = create_engine(database_url(), pool_pre_ping=True)
        _session_factory = sessionmaker(_engine)
    return _engine


def session_factory() -> sessionmaker[Session]:
    get_engine()
    if _session_factory is None:
        raise RuntimeError("database session factory is not ready")
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
