from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from supportsense.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {},
)
SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    with SessionFactory() as session:
        yield session


def create_development_schema() -> None:
    if settings.environment == "production":
        raise RuntimeError("Production schemas must be managed with Alembic migrations")
    from supportsense import db_models  # noqa: F401

    Base.metadata.create_all(engine)
