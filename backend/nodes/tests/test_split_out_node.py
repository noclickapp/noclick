"""Tests for the dedicated Split Out node (one item per array
element, keeping the split field's name)."""

import pytest

from nodes.split_out_node import SplitOutNode, SplitOutNodeConfig, SplitOutConfigModel


def _node(input_data, **cfg):
    config = SplitOutNodeConfig(config=SplitOutConfigModel(input_data=input_data, **cfg))
    return SplitOutNode(node_id="so", node_type="split-out", node_data={}, config=config)


@pytest.mark.asyncio
async def test_scalars_keep_field_name():
    out = await _node({"tags": ["a", "b"]}, fields_to_split="tags").execute({})
    assert out["status"] == "success"
    assert out["count"] == 2
    assert out["items"] == [{"tags": "a"}, {"tags": "b"}]


@pytest.mark.asyncio
async def test_objects_keep_field_name():
    out = await _node({"items": [{"x": 1}, {"x": 2}]}, fields_to_split="items").execute({})
    assert out["items"] == [{"items": {"x": 1}}, {"items": {"x": 2}}]


@pytest.mark.asyncio
async def test_include_all_other_fields():
    out = await _node(
        {"tags": ["a", "b"], "id": 7, "name": "x"}, fields_to_split="tags", include="all"
    ).execute({})
    assert out["items"] == [
        {"id": 7, "name": "x", "tags": "a"},
        {"id": 7, "name": "x", "tags": "b"},
    ]


@pytest.mark.asyncio
async def test_include_selected():
    out = await _node(
        {"tags": ["a"], "id": 7, "name": "x"},
        fields_to_split="tags",
        include="selected",
        fields_to_include="name",
    ).execute({})
    assert out["items"] == [{"name": "x", "tags": "a"}]


@pytest.mark.asyncio
async def test_destination_field_renames():
    out = await _node(
        {"items": [{"x": 1}]}, fields_to_split="items", destination_field="row"
    ).execute({})
    assert out["items"] == [{"row": {"x": 1}}]


@pytest.mark.asyncio
async def test_multiple_fields_zip():
    out = await _node(
        {"a": [1, 2], "b": ["x", "y"]}, fields_to_split="a, b"
    ).execute({})
    assert out["items"] == [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]


@pytest.mark.asyncio
async def test_dot_notation():
    out = await _node({"data": {"items": [{"k": 1}]}}, fields_to_split="data.items").execute({})
    assert out["items"] == [{"items": {"k": 1}}]


@pytest.mark.asyncio
async def test_bare_array_spreads_objects():
    out = await _node([{"a": 1}, {"a": 2}]).execute({})
    assert out["items"] == [{"a": 1}, {"a": 2}]


@pytest.mark.asyncio
async def test_non_array_field_fails_loud():
    out = await _node({"items": {"not": "array"}}, fields_to_split="items").execute({})
    assert out["status"] == "error"
    assert "not an array" in out["error"]


@pytest.mark.asyncio
async def test_unresolved_reference_errors():
    out = await _node("{{node.items}}", fields_to_split="items").execute({})
    assert out["status"] == "error"
    assert "was not resolved" in out["error"]
