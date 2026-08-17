"""API surface tests — health, status, OpenAPI."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cognitive.gateway.app import create_app


@pytest.fixture
def api_client(app_and_services, tenant_a_headers):
    app, *_ = app_and_services
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, tenant_a_headers


def test_health_public(api_client):
    client, _ = api_client
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "prosperfy-cognitive"
    assert "version" in body
    assert "environment" in body
    assert "postgresql" not in str(body).lower()


def test_openapi_json(api_client):
    client, _ = api_client
    r = client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert schema["info"]["title"] == "Prosperfy Cognitive API"
    assert "/health" in schema["paths"]
    assert "/v1/status" in schema["paths"]
    assert "/v1/capabilities" in schema["paths"]


def test_status_authenticated(api_client):
    client, headers = api_client
    r = client.get("/v1/status", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["healthy"] is True
    assert body["tenant_id"] == "tenant-a"
    assert body["runtime_mode"] == "in_memory"
    assert body["registry_loaded"] is True
    assert body["capabilities_count"] >= 1
    assert "postgresql://" not in str(body)


def test_list_capabilities(api_client):
    client, headers = api_client
    r = client.get("/v1/capabilities", headers=headers)
    assert r.status_code == 200
    caps = r.json()
    assert isinstance(caps, list)
    assert any(c["id"] == "infra.inspect" for c in caps)
