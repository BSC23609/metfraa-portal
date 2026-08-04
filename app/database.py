"""Database connection and session management."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from .config import get_settings

settings = get_settings()

# SQLite needs special connect args
connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

import os as _os
if _os.getenv("VERCEL") and not settings.database_url.startswith("sqlite"):
    # Serverless: use Neon's POOLED endpoint (-pooler host) + NullPool locally.
    from sqlalchemy.pool import NullPool

    engine = create_engine(
        settings.database_url,
        connect_args=connect_args,
        poolclass=NullPool,
    )
else:
    engine = create_engine(
        settings.database_url,
        connect_args=connect_args,
        pool_pre_ping=True,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency for DB sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
