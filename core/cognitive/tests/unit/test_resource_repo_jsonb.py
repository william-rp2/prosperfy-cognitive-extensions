"""tests/unit/test_resource_repo_jsonb.py — Regressão JSONB em TenantResourceRepository."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from cognitive.db.repositories.resource_repo import (
    TenantResourceRepository,
    _row_to_tenant_resource,
)


@pytest.mark.parametrize(
    "resolved_params",
    [
        {},
        {"host": "vps.prosperfy.com.br", "port": 22},
        {"resource": {"name": "prosperfy-main", "type": "server"}},
        {"items": [1, 2, 3]},
        {"allowed": True, "reason": None},
        {"message": "ação concluída"},
        {"quote": 'say "hello"', "slash": "path/to/file"},
    ],
)
def test_row_to_tenant_resource_from_json_string(resolved_params):
    row = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "resource_key": "prosperfy-main",
        "resource_type": "vps",
        "resolved_params": json.dumps(resolved_params, ensure_ascii=False),
        "active": True,
    }
    resource = _row_to_tenant_resource(row)
    assert resource.resolved_params == resolved_params
    assert isinstance(resource.resolved_params, dict)


def test_row_to_tenant_resource_from_python_dict():
    params = {"host": "vps.prosperfy.com.br"}
    row = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "resource_key": "prosperfy-main",
        "resource_type": "vps",
        "resolved_params": params,
        "active": True,
    }
    resource = _row_to_tenant_resource(row)
    assert resource.resolved_params == params


@pytest.mark.asyncio
async def test_resolve_deserializes_json_string_from_driver():
    params = {"host": "vps.prosperfy.com.br", "nested": {"a": 1}}
    row = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "resource_key": "prosperfy-main",
        "resource_type": "vps",
        "resolved_params": json.dumps(params),
        "active": True,
    }
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=row)

    repo = TenantResourceRepository()
    with patch(
        "cognitive.db.repositories.resource_repo.tenant_transaction"
    ) as mock_tx:
        mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_tx.return_value.__aexit__ = AsyncMock(return_value=False)
        resource = await repo.resolve(str(uuid.uuid4()), "prosperfy-main")

    assert resource is not None
    assert resource.resolved_params == params
    assert isinstance(resource.resolved_params, dict)


@pytest.mark.asyncio
async def test_upsert_serializes_jsonb_param():
    params = {"host": "vps", "items": [1, 2], "ok": True, "reason": None}
    row = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "resource_key": "prosperfy-main",
        "resource_type": "vps",
        "resolved_params": json.dumps(params),
        "active": True,
    }
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=row)

    repo = TenantResourceRepository()
    with patch(
        "cognitive.db.repositories.resource_repo.admin_connection"
    ) as mock_admin:
        mock_admin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_admin.return_value.__aexit__ = AsyncMock(return_value=False)
        resource = await repo.upsert(
            str(uuid.uuid4()), "prosperfy-main", "vps", params
        )

    insert_args = mock_conn.fetchrow.call_args[0][1:]
    serialized = insert_args[3]
    assert isinstance(serialized, str)
    assert json.loads(serialized) == params
    assert resource.resolved_params == params
