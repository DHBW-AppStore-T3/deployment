"""The API description the TypeScript client is generated from (plan AP6).

Operation ids are the route functions' names in camelCase (``list_my_courses``
→ ``listMyCourses``), the scheme the Go services' clients use. FastAPI's
default adds path and method (``list_my_courses_me_courses_get``), which
changes with every moved route and makes unreadable client functions; a
renamed Python function is the one thing that changes an id now, and the
contract check (``make openapi-check``) shows it.

``python -m appstore_api.openapi`` prints the description; ``make openapi``
writes it to ``openapi.json`` at the repository root, where it is committed.
"""

from __future__ import annotations

import json
import sys

from fastapi.routing import APIRoute


def operation_id(route: APIRoute) -> str:
    """The route function's name in camelCase; FastAPI's ``generate_unique_id_function``."""
    first, *rest = route.name.split("_")
    return first + "".join(part[:1].upper() + part[1:] for part in rest)


def main() -> None:
    """Print the OpenAPI description as JSON to stdout."""
    from appstore_api.main import app

    json.dump(app.openapi(), sys.stdout, indent=2, ensure_ascii=False, sort_keys=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
