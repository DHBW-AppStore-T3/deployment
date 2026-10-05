"""Time helpers: re-exports :func:`appstore_shared.models.utcnow` (current UTC time, naive) for the API."""

from appstore_shared.models import utcnow

__all__ = ["utcnow"]
