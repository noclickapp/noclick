"""WorkflowNode.validate_config must not flag a field holding a {{ ... }}
reference/expression as the wrong type — its value is resolved at runtime, so the
type is unknown at edit time. Genuine errors on other fields still surface.
"""

from pydantic import BaseModel

from nodes.core.base import WorkflowNode


class _Cfg(BaseModel):
    count: int
    name: str


class _FakeNode(WorkflowNode):
    __abstractmethods__ = frozenset()

    @classmethod
    def get_config_model(cls):
        return _Cfg


def test_expression_on_strict_int_field_is_valid():
    result = _FakeNode.validate_config({"count": "{{ $('n').x }}", "name": "ok"})
    assert result["valid"] is True
    assert result["errors"] == []


def test_legacy_reference_on_strict_int_field_is_valid():
    result = _FakeNode.validate_config({"count": "{{n.count}}", "name": "ok"})
    assert result["valid"] is True


def test_genuinely_bad_value_still_invalid():
    result = _FakeNode.validate_config({"count": "not-a-number", "name": "ok"})
    assert result["valid"] is False
    assert result["errors"]


def test_real_error_surfaces_alongside_expression_field():
    # Expression field is excused, but the missing required field still errors.
    result = _FakeNode.validate_config({"count": "{{ $('n').x }}"})
    assert result["valid"] is False
    assert any("name" in e for e in result["errors"])
