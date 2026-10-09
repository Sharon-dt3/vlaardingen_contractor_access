"""SQLAlchemy engine and session lifecycle."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=300,
)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


# PUBLIC_INTERFACE
def get_db() -> Generator[Session, None, None]:
    """Yield a request-scoped database session and always close it."""

    database = SessionLocal()
    try:
        yield database
    finally:
        database.close()
