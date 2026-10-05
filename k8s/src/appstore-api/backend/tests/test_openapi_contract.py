"""The API description the UI's client is generated from (plan AP6)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from appstore_api.main import app

pytestmark = pytest.mark.unit

COMMITTED = Path(__file__).resolve().parents[2] / "openapi.json"


def _operations(spec):
    return [op for path in spec["paths"].values() for op in path.values()]


def test_operation_ids_are_unique_camel_case_verbs():
    ids = [op["operationId"] for op in _operations(app.openapi())]

    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[a-z]+(?:[A-Z][a-z0-9]*)*", i) for i in ids), ids
    assert {"listMyCourses", "createDeployment", "saveMyCredential", "listNetworks"} <= set(ids)


def test_internal_endpoints_are_not_described():
    assert not [p for p in app.openapi()["paths"] if p.startswith("/internal")]


def test_the_committed_description_matches_the_code():
    """``make openapi-check`` compares byte for byte; this catches it earlier, in the tests."""
    committed = json.loads(COMMITTED.read_text())
    generated = app.openapi()
    # The committed file carries the release version; the tests run unbundled.
    generated = {**generated, "info": {**generated["info"], "version": committed["info"]["version"]}}

    assert generated == committed, "openapi.json is stale: run 'make openapi' and commit it"


def test_the_description_is_served_where_the_go_services_serve_theirs(unauth_client):
    response = unauth_client.get("/swagger.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "AppStore API"
