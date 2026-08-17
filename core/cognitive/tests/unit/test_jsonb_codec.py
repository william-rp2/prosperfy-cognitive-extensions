"""tests/unit/test_jsonb_codec.py — Contrato JSONB centralizado."""

from __future__ import annotations

import json

import pytest

from cognitive.db.jsonb_codec import (
    JsonbCodecError,
    deserialize_jsonb,
    deserialize_jsonb_object,
    serialize_jsonb,
)


class TestSerializeJsonb:
    def test_empty_object(self):
        assert serialize_jsonb({}) == "{}"

    def test_simple_object(self):
        assert serialize_jsonb({"resource": "prosperfy-main"}) == '{"resource":"prosperfy-main"}'

    def test_nested_object(self):
        payload = {"resource": {"name": "prosperfy-main", "type": "server"}}
        assert json.loads(serialize_jsonb(payload)) == payload

    def test_array(self):
        payload = {"items": [1, 2, 3]}
        assert json.loads(serialize_jsonb(payload)) == payload

    def test_boolean_and_json_null(self):
        payload = {"allowed": True, "reason": None}
        assert json.loads(serialize_jsonb(payload)) == payload

    def test_unicode(self):
        payload = {"message": "ação concluída"}
        result = serialize_jsonb(payload)
        assert "ação concluída" in result
        assert json.loads(result) == payload

    def test_special_characters_escaping(self):
        payload = {
            "quote": 'say "hello"',
            "slash": "path/to/file",
            "backslash": "a\\b",
        }
        serialized = serialize_jsonb(payload)
        assert json.loads(serialized) == payload

    def test_list_root(self):
        payload = [1, {"a": 2}, None]
        assert json.loads(serialize_jsonb(payload)) == payload

    def test_sql_null(self):
        assert serialize_jsonb(None) is None

    def test_rejects_scalar(self):
        with pytest.raises(JsonbCodecError):
            serialize_jsonb("not-a-dict")  # type: ignore[arg-type]


class TestDeserializeJsonb:
    def test_from_json_string(self):
        assert deserialize_jsonb('{"resource":"prosperfy-main"}') == {
            "resource": "prosperfy-main"
        }

    def test_from_python_dict(self):
        value = {"resource": "prosperfy-main"}
        assert deserialize_jsonb(value) is value

    def test_from_python_list(self):
        value = [1, 2, 3]
        assert deserialize_jsonb(value) is value

    def test_sql_null(self):
        assert deserialize_jsonb(None) is None

    def test_json_null_in_object(self):
        assert deserialize_jsonb('{"reason": null}') == {"reason": None}

    def test_unicode_round_trip(self):
        payload = {"message": "ação concluída"}
        assert deserialize_jsonb(serialize_jsonb(payload)) == payload

    def test_nested_round_trip(self):
        payload = {"resource": {"name": "prosperfy-main", "type": "server"}}
        assert deserialize_jsonb(serialize_jsonb(payload)) == payload

    def test_array_round_trip(self):
        payload = {"items": [1, 2, 3]}
        assert deserialize_jsonb(serialize_jsonb(payload)) == payload

    def test_special_characters_round_trip(self):
        payload = {"quote": 'say "hello"', "slash": "path/to/file"}
        assert deserialize_jsonb(serialize_jsonb(payload)) == payload

    def test_rejects_int(self):
        with pytest.raises(JsonbCodecError):
            deserialize_jsonb(42)


class TestDeserializeJsonbObject:
    def test_from_json_string(self):
        assert deserialize_jsonb_object('{"host":"vps"}') == {"host": "vps"}

    def test_from_python_dict(self):
        assert deserialize_jsonb_object({"host": "vps"}) == {"host": "vps"}

    def test_sql_null_returns_empty_dict(self):
        assert deserialize_jsonb_object(None) == {}

    def test_rejects_json_array(self):
        with pytest.raises(JsonbCodecError):
            deserialize_jsonb_object("[1,2,3]")
