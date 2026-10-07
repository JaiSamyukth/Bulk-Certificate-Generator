"""Database engine / session helpers (SQLAlchemy 2.0)."""

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def create_db_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    is_sqlite = url.get_backend_name() == "sqlite"

    kwargs: dict = {"pool_pre_ping": True}
    if is_sqlite:
        # Worker threads share the engine, so allow cross-thread connections and
        # wait (rather than fail) when another connection holds the write lock.
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        if url.database and url.database != ":memory:":
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(database_url, **kwargs)

    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record):  # pragma: no cover - trivial
            cursor = dbapi_connection.cursor()
            # WAL lets API reads proceed while a worker is writing.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False)
