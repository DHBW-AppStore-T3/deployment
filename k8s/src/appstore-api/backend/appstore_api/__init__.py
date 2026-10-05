"""AppStore API: the FastAPI service behind the AppStore pages of self-service-ui.

The application object lives in :mod:`appstore_api.main`; this package only
exposes ``__version__``.
"""

from pathlib import Path

# `make bundle` copies the repository's VERSION file next to this one, the way
# the Go services embed theirs; a plain checkout that skipped it reports "dev".
try:
    __version__ = (Path(__file__).parent / "VERSION").read_text().strip()
except OSError:
    __version__ = "dev"
