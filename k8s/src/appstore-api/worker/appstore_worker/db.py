"""Database access for the worker process (never for the jobs it runs)."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import settings

# One connection per concurrently running job for its events, one for its
# heartbeat, plus the claim loop.
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=2 * settings.WORKER_CONCURRENCY + 1,
    max_overflow=2,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
