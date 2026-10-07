"""Typed UI values must survive the real native config parser unchanged."""

from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.reddit_node import RedditNode


class TypedFields(BaseModel):
    model_config = ConfigDict(strict=True)
    interval: Literal[0, 1, 5] = 1
    active: StrictBool | None = None
    numbers: list[StrictInt] = []
    flags: list[StrictBool] = []


class TypedFieldsNode(WorkflowNode):
    @classmethod
    def get_config_model(cls):
        return NodeConfig[TypedFields, BaseModel]

    async def execute(self, inputs):
        raise AssertionError('This config regression has no execution or provider transport')


@pytest.mark.parametrize('value', [1, 2, None])
def test_actual_reddit_nullable_numeric_enum_accepts_typed_values(value):
    parsed = RedditNode.parse_config({'config': {'operation': 'sticky_or_unsticky_post', 'thing_id': 't3_fixture', 'num': value}})
    assert parsed.config.num == value
    assert type(parsed.config.num) is type(value)


@pytest.mark.parametrize('value', ['1', '2', '2garbage', 3, [], {}])
def test_actual_reddit_numeric_enum_refuses_strings_and_unknown_choices(value):
    with pytest.raises(ValueError):
        RedditNode.parse_config({'config': {'operation': 'sticky_or_unsticky_post', 'thing_id': 't3_fixture', 'num': value}})


@pytest.mark.parametrize('active', [True, False, None])
def test_native_parser_preserves_boolean_null_and_array_item_types(active):
    data = {'interval': 0, 'active': active, 'numbers': [0, 5], 'flags': [False, True]}
    parsed = TypedFieldsNode.parse_config({'config': data})
    assert parsed.config.model_dump() == data
    assert type(parsed.config.interval) is int
    assert all(type(value) is int for value in parsed.config.numbers)
    assert all(type(value) is bool for value in parsed.config.flags)


@pytest.mark.parametrize('change', [
    {'interval': '5'}, {'interval': '5garbage'}, {'interval': 2},
    {'active': 'false'}, {'active': 0}, {'active': 'no'},
    {'numbers': ['5']}, {'numbers': [True]}, {'numbers': '5'},
    {'flags': ['false']}, {'flags': [0]}, {'flags': 'false'},
])
def test_native_parser_refuses_string_coercion_and_wrong_scalar_array_types(change):
    with pytest.raises(ValueError):
        TypedFieldsNode.parse_config({'config': {'interval': 5, 'active': False, 'numbers': [5], 'flags': [False], **change}})
