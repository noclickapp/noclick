"""Unit tests for helpers in utils/node_schema_tracker.py.

Covers schema extraction, value clipping, the suggested-refs validator, and
the deterministic hash. The suggested-refs tests cover the edition/credential
boundary; DB upserts are exercised via integration flows.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from utils import node_schema_tracker
from utils.node_schema_tracker import (
    _generate_suggested_refs,
    clip_values,
    compute_schema_hash,
    extract_schema,
    infer_type,
    _validate_suggested_refs,
)
from coder.workflow.workflow_schema import all_schema_paths


class TestInferType:
    def test_primitives(self):
        assert infer_type(None) == "null"
        assert infer_type(True) == "boolean"
        assert infer_type(0) == "integer"
        assert infer_type(1.5) == "float"
        assert infer_type("hi") == "string"
        assert infer_type([]) == "array"
        assert infer_type({}) == "object"

    def test_bool_not_int(self):
        # bool is a subclass of int — this caught a real bug in the original.
        assert infer_type(False) == "boolean"


class TestExtractSchema:
    def test_flat_dict(self):
        assert extract_schema({"name": "John", "age": 30}) == {
            "name": "string", "age": "integer"
        }

    def test_array_of_objects_merges_keys(self):
        # Field present only on item 2 should still appear in the schema.
        data = [{"a": 1}, {"a": 2, "b": "x"}]
        assert extract_schema(data) == [{"a": "integer", "b": "string"}]

    def test_two_d_array_collapses(self):
        # Column counts vary between datasets; just mark as 2D.
        assert extract_schema([["a", "b"], ["c", "d"]]) == [[]]


class TestClipValues:
    def test_clips_long_strings(self):
        clipped = clip_values({"text": "a" * 200}, max_string=10)
        assert clipped["text"] == "a" * 10 + "…"

    def test_keeps_short_strings(self):
        assert clip_values({"name": "hi"}) == {"name": "hi"}

    def test_sample_array_to_first_non_null(self):
        # Sampling lets the LLM see what's inside without paying for the whole list.
        assert clip_values([None, {"a": 1}, {"a": 2}]) == [{"a": 1}]

    def test_recurses_into_nested(self):
        data = {"user": {"name": "alice", "tags": ["x", "y"]}}
        assert clip_values(data) == {"user": {"name": "alice", "tags": ["x"]}}


class TestComputeSchemaHash:
    def test_deterministic(self):
        schema = {"a": "string", "b": "integer"}
        h1 = compute_schema_hash("t", "op", schema)
        h2 = compute_schema_hash("t", "op", schema)
        assert h1 == h2

    def test_key_order_stable(self):
        # sort_keys=True is what makes this stable across dict insertion order.
        a = {"a": "string", "b": "integer"}
        b = {"b": "integer", "a": "string"}
        assert compute_schema_hash("t", "op", a) == compute_schema_hash("t", "op", b)

    def test_different_inputs_differ(self):
        assert compute_schema_hash("t", "op", {"a": "string"}) != \
            compute_schema_hash("t", "op", {"b": "string"})


class TestValidateSuggestedRefs:
    @pytest.fixture
    def schema(self):
        return {"rows": [{"id": "integer", "name": "string"}], "count": "integer"}

    @pytest.fixture
    def valid_paths(self, schema):
        return all_schema_paths(schema)

    def test_happy_path(self, valid_paths):
        parsed = {"refs": [
            {"path": "rows[].name", "label": "Name", "description": "Person's name."},
            {"path": "count", "label": "Total", "description": "How many rows came back."},
        ]}
        result = _validate_suggested_refs(parsed, valid_paths)
        assert result is not None
        assert len(result) == 2
        assert result[0]["path"] == "rows[].name"

    def test_rejects_hallucinated_path(self, valid_paths):
        parsed = {"refs": [
            {"path": "rows[].nonexistent", "label": "Nope", "description": "Made up."},
        ]}
        assert _validate_suggested_refs(parsed, valid_paths) is None

    def test_rejects_duplicates(self, valid_paths):
        parsed = {"refs": [
            {"path": "count", "label": "Total", "description": "First."},
            {"path": "count", "label": "Again", "description": "Dup."},
        ]}
        assert _validate_suggested_refs(parsed, valid_paths) is None

    def test_rejects_empty_strings(self, valid_paths):
        parsed = {"refs": [
            {"path": "count", "label": "", "description": "Bad."},
        ]}
        assert _validate_suggested_refs(parsed, valid_paths) is None

    def test_rejects_wrong_shape(self, valid_paths):
        assert _validate_suggested_refs({"refs": "not a list"}, valid_paths) is None
        assert _validate_suggested_refs({"wrong": []}, valid_paths) is None
        assert _validate_suggested_refs([], valid_paths) is None
        assert _validate_suggested_refs(None, valid_paths) is None

    def test_rejects_empty_refs(self, valid_paths):
        assert _validate_suggested_refs({"refs": []}, valid_paths) is None

    def test_trims_whitespace(self, valid_paths):
        parsed = {"refs": [
            {"path": "  count  ", "label": " Total ", "description": " Sum. "},
        ]}
        result = _validate_suggested_refs(parsed, valid_paths)
        assert result == [{"path": "count", "label": "Total", "description": "Sum."}]


class TestGenerateSuggestedRefsCredentialGate:
    @staticmethod
    def _valid_response():
        content = json.dumps(
            {
                "refs": [
                    {
                        "path": "name",
                        "label": "Name",
                        "description": "The displayed name.",
                    }
                ],
            }
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("key_value", [None, "", "   "])
    async def test_keyless_local_skips_without_calling_litellm(
        self,
        monkeypatch,
        key_value,
    ):
        monkeypatch.setenv("NOCLICK_LOCAL", "1")
        if key_value is None:
            # Explicit deletion keeps an ambient developer-shell key from
            # turning this no-egress regression into a false positive.
            monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        else:
            monkeypatch.setenv("OPENROUTER_API_KEY", key_value)
        # These are upstream routing choices *behind* OpenRouter, not valid
        # credentials for the fixed openrouter/... LiteLLM model.
        monkeypatch.setenv("GROQ_API_KEY", "ambient-groq-key")
        monkeypatch.setenv("CEREBRAS_API_KEY", "ambient-cerebras-key")
        completion = AsyncMock()
        monkeypatch.setattr(node_schema_tracker.litellm, "acompletion", completion)

        result = await _generate_suggested_refs(
            "automation-test",
            "read",
            {"name": "string"},
            {"name": "Ada"},
        )

        assert result is None
        completion.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_configured_local_calls_with_explicit_openrouter_key(
        self, monkeypatch
    ):
        monkeypatch.setenv("NOCLICK_LOCAL", "1")
        monkeypatch.setenv("OPENROUTER_API_KEY", "operator-configured-key")
        completion = AsyncMock(return_value=self._valid_response())
        monkeypatch.setattr(node_schema_tracker.litellm, "acompletion", completion)

        result = await _generate_suggested_refs(
            "automation-test",
            "read",
            {"name": "string"},
            {"name": "Ada"},
        )

        assert result == [
            {
                "path": "name",
                "label": "Name",
                "description": "The displayed name.",
            }
        ]
        assert completion.await_count == 1
        assert completion.await_args.kwargs["api_key"] == "operator-configured-key"

    @pytest.mark.asyncio
    async def test_hosted_behavior_does_not_require_environment_key(self, monkeypatch):
        monkeypatch.delenv("NOCLICK_LOCAL", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        completion = AsyncMock(return_value=self._valid_response())
        monkeypatch.setattr(node_schema_tracker.litellm, "acompletion", completion)

        result = await _generate_suggested_refs(
            "automation-test",
            "read",
            {"name": "string"},
            {"name": "Ada"},
        )

        assert result is not None
        assert completion.await_count == 1
        assert "api_key" not in completion.await_args.kwargs
