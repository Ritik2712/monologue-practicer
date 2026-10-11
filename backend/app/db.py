"""SQLite engine and session setup. Schema changes go through Alembic migrations."""

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    is_sqlite = url.get_backend_name() == "sqlite"
    if is_sqlite and url.database and url.database != ":memory:":
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(url, connect_args={"check_same_thread": False} if is_sqlite else {})

    if is_sqlite:
        # The API and the worker are separate processes sharing one file.
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
