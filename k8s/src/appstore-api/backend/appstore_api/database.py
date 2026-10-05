"""The SQLAlchemy engine and the per-request session dependency ``get_db``.

Routers and ``auth.py`` take sessions via ``Depends(get_db)``; scripts such as
``dev_seed`` use ``SessionLocal`` directly.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from appstore_api.config import settings

# Re-exported: alembic and the tests take the metadata from here.
from appstore_shared.models import Base

# ----------------------------------------------------------------
# DATABASE ENGINE
# ----------------------------------------------------------------
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,  # Verify connections before using
    pool_size=5,
    max_overflow=10
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ----------------------------------------------------------------
# DEPENDENCY
# ----------------------------------------------------------------
def get_db():
    """FastAPI dependency: one session per request, closed afterwards.

    Nothing is committed here; handlers and crud functions commit explicitly.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


__all__ = ["Base", "engine", "SessionLocal", "get_db"]
