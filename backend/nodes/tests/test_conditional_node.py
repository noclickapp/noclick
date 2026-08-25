"""
Tests for Conditional node.
Verifies if_else branching operations.
"""

import pytest
import json
from nodes.conditional_node import (
    ConditionalNode,
    ConditionalNodeConfig,
    ConditionalInnerConfig,
    ConditionalOperator,
)


# Test data fixtures
@pytest.fixture
def sample_user():
    """Sample user object"""
    return {
        "name": "Alice",
        "age": 30,
        "status": "active",
        "role": "admin",
        "email": "alice@example.com",
    }


@pytest.fixture
def sample_nested_data():
    """Sample data with nested structure"""
    return {
        "user": {
            "profile": {
                "name": "Bob",
                "settings": {
                    "theme": "dark",
                    "notifications": True,
                }
            },
            "status": "inactive",
        },
        "metadata": {
            "version": "2.0",
        }
    }


# ===== IF/ELSE OPERATION TESTS =====

@pytest.mark.asyncio
async def test_if_else_equals_true(sample_user):
    """Test if/else with equals operator - condition is true"""
    config = ConditionalNodeConfig(
        config=ConditionalInnerConfig(
            input_data=json.dumps(sample_user),
            condition_field="status",
            condition_operator=ConditionalOperator.EQUALS,
            condition_value="active",
        )
    )

    node = ConditionalNode(
        node_id="conditional_1",
        node_type="conditional",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["status"] == "success"
    assert result["operation"] == "if_else"
    assert result["condition_result"] is True
    assert result["output_handle"] == "true"
    assert result["data"]["name"] == "Alice"


@pytest.mark.asyncio
async def test_if_else_equals_false(sample_user):
    """Test if/else with equals operator - condition is false"""
    config = ConditionalNodeConfig(
        config=ConditionalInnerConfig(
            input_data=json.dumps(sample_user),
            condition_field="status",
            condition_operator=ConditionalOperator.EQUALS,
            condition_value="inactive",
        )
    )

    node = ConditionalNode(
        node_id="conditional_2",
        node_type="conditional",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["status"] == "success"
    assert result["condition_result"] is False
    assert result["output_handle"] == "false"


@pytest.mark.asyncio
async def test_if_else_greater_than(sample_user):
    """Test if/else with greater_than operator"""
    config = ConditionalNodeConfig(
        config=ConditionalInnerConfig(
            input_data=json.dumps(sample_user),
            condition_field="age",
            condition_operator=ConditionalOperator.GREATER_THAN,
            condition_value="25",
        )
    )

    node = ConditionalNode(
        node_id="conditional_3",
        node_type="conditional",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["condition_result"] is True
    assert result["output_handle"] == "true"


@pytest.mark.asyncio
async def test_if_else_less_than_or_equal(sample_user):
    """Test if/else with less_than_or_equal operator"""
    config = ConditionalNodeConfig(
        config=ConditionalInnerConfig(
            input_data=json.dumps(sample_user),
            condition_field="age",
            condition_operator=ConditionalOperator.LESS_THAN_OR_EQUAL,
            condition_value="30",
        )
    )

    node = ConditionalNode(
        node_id="conditional_4",
        node_type="conditional",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["condition_result"] is True
    assert result["output_handle"] == "true"


@pytest.mark.asyncio
async def test_if_else_contains(sample_user):
    """Test if/else with contains operator"""
    config = ConditionalNodeConfig(
        config=ConditionalInnerConfig(
            input_data=json.dumps(sample_user),
            condition_field="email",
            condition_operator=ConditionalOperator.CONTAINS,
            condition_value="example.com",
        )
    )

    node = ConditionalNode(
        node_id="conditional_5",
        node_type="conditional",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["condition_result"] is True
    assert result["output_handle"] == "true"


@pytest.mark.asyncio
async def test_if_else_not_contains(sample_user):
    """Test if/else with not_contains operator"""
    config = ConditionalNodeConfig(
        config=ConditionalInnerConfig(
            input_data=json.dumps(sample_user),
            condition_field="email",
            condition_operator=ConditionalOperator.NOT_CONTAINS,
            condition_value="gmail.com",
        )
    )

    node = ConditionalNode(
        node_id="conditional_6",
        node_type="conditional",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["condition_result"] is True


@pytest.mark.asyncio
async def test_if_else_starts_with(sample_user):
    """Test if/else with starts_with operator"""
    config = ConditionalNodeConfig(
        config=ConditionalInnerConfig(
            input_data=json.dumps(sample_user),
            condition_field="name",
            condition_operator=ConditionalOperator.STARTS_WITH,
            condition_value="Ali",
        )
    )

    node = ConditionalNode(
        node_id="conditional_7",
        node_type="conditional",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["condition_result"] is True


@pytest.mark.asyncio
async def test_if_else_ends_with(sample_user):
    """Test if/else with ends_with operator"""
    config = ConditionalNodeConfig(
        config=ConditionalInnerConfig(
            input_data=json.dumps(sample_user),
            condition_field="email",
            condition_operator=ConditionalOperator.ENDS_WITH,
            condition_value=".com",
        )
    )

    node = ConditionalNode(
        node_id="conditional_8",
        node_type="conditional",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["condition_result"] is True


@pytest.mark.asyncio
async def test_if_else_is_empty_false(sample_user):
    """Test if/else with is_empty operator - field is not empty"""
    config = ConditionalNodeConfig(
        config=ConditionalInnerConfig(
            input_data=json.dumps(sample_user),
            condition_field="name",
            condition_operator=ConditionalOperator.IS_EMPTY,
        )
    )

    node = ConditionalNode(
        node_id="conditional_9",
        node_type="conditional",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["condition_result"] is False
    assert result["output_handle"] == "false"


@pytest.mark.asyncio
async def test_if_else_is_empty_true():
    """Test if/else with is_empty operator - field is empty"""
    data = {"name": "", "description": None}
    config = ConditionalNodeConfig(
        config=ConditionalInnerConfig(
            input_data=json.dumps(data),
            condition_field="name",
            condition_operator=ConditionalOperator.IS_EMPTY,
        )
    )

    node = ConditionalNode(
        node_id="conditional_10",
        node_type="conditional",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["condition_result"] is True
    assert result["output_handle"] == "true"


@pytest.mark.asyncio
async def test_if_else_is_not_empty(sample_user):
    """Test if/else with is_not_empty operator"""
    config = ConditionalNodeConfig(
        config=ConditionalInnerConfig(
            input_data=json.dumps(sample_user),
            condition_field="email",
            condition_operator=ConditionalOperator.IS_NOT_EMPTY,
        )
    )

    node = ConditionalNode(
        node_id="conditional_11",
        node_type="conditional",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["condition_result"] is True


@pytest.mark.asyncio
async def test_if_else_is_true():
    """Test if/else with is_true operator"""
    data = {"enabled": True, "name": "Test"}
    config = ConditionalNodeConfig(
        config=ConditionalInnerConfig(
            input_data=json.dumps(data),
            condition_field="enabled",
            condition_operator=ConditionalOperator.IS_TRUE,
        )
    )

    node = ConditionalNode(
        node_id="conditional_12",
        node_type="conditional",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["condition_result"] is True


@pytest.mark.asyncio
async def test_if_else_is_false():
    """Test if/else with is_false operator"""
    data = {"enabled": False, "name": "Test"}
    config = ConditionalNodeConfig(
        config=ConditionalInnerConfig(
            input_data=json.dumps(data),
            condition_field="enabled",
            condition_operator=ConditionalOperator.IS_FALSE,
        )
    )

    node = ConditionalNode(
        node_id="conditional_13",
        node_type="conditional",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["condition_result"] is True


@pytest.mark.asyncio
async def test_if_else_regex_match():
    """Test if/else with regex_match operator"""
    data = {"phone": "+1-555-123-4567"}
    config = ConditionalNodeConfig(
        config=ConditionalInnerConfig(
            input_data=json.dumps(data),
            condition_field="phone",
            condition_operator=ConditionalOperator.REGEX_MATCH,
            condition_value=r"\+\d+-\d{3}-\d{3}-\d{4}",
        )
    )

    node = ConditionalNode(
        node_id="conditional_14",
        node_type="conditional",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["condition_result"] is True


@pytest.mark.asyncio
async def test_if_else_case_insensitive(sample_user):
    """Test if/else with case insensitive comparison"""
    config = ConditionalNodeConfig(
        config=ConditionalInnerConfig(
            input_data=json.dumps(sample_user),
            condition_field="status",
            condition_operator=ConditionalOperator.EQUALS,
            condition_value="ACTIVE",  # Uppercase
            case_sensitive=False,
        )
    )

    node = ConditionalNode(
        node_id="conditional_15",
        node_type="conditional",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["condition_result"] is True


@pytest.mark.asyncio
async def test_if_else_case_sensitive(sample_user):
    """Test if/else with case sensitive comparison"""
    config = ConditionalNodeConfig(
        config=ConditionalInnerConfig(
            input_data=json.dumps(sample_user),
            condition_field="status",
            condition_operator=ConditionalOperator.EQUALS,
            condition_value="ACTIVE",  # Uppercase
            case_sensitive=True,
        )
    )

    node = ConditionalNode(
        node_id="conditional_16",
        node_type="conditional",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["condition_result"] is False  # "active" != "ACTIVE"


@pytest.mark.asyncio
async def test_if_else_nested_field(sample_nested_data):
    """Test if/else with nested field access"""
    config = ConditionalNodeConfig(
        config=ConditionalInnerConfig(
            input_data=json.dumps(sample_nested_data),
            condition_field="user.profile.settings.theme",
            condition_operator=ConditionalOperator.EQUALS,
            condition_value="dark",
        )
    )

    node = ConditionalNode(
        node_id="conditional_17",
        node_type="conditional",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["condition_result"] is True
    assert result["output_handle"] == "true"


@pytest.mark.asyncio
async def test_if_else_no_field_evaluates_entire_input():
    """Test if/else evaluating entire input when no field specified"""
    data = "active"  # Direct string value
    config = ConditionalNodeConfig(
        config=ConditionalInnerConfig(
            input_data=json.dumps(data),
            condition_field=None,  # No field - evaluate entire input
            condition_operator=ConditionalOperator.EQUALS,
            condition_value="active",
        )
    )

    node = ConditionalNode(
        node_id="conditional_18",
        node_type="conditional",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["condition_result"] is True


# ===== ERROR HANDLING TESTS =====

@pytest.mark.asyncio
async def test_no_config():
    """Test handling missing config"""
    node = ConditionalNode(
        node_id="conditional_25",
        node_type="conditional",
        node_data={},
        config=None,
    )

    with pytest.raises(ValueError) as exc_info:
        await node.execute({})

    assert "Configuration required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_unresolved_reference():
    """Test handling unresolved reference"""
    config = ConditionalNodeConfig(
        config=ConditionalInnerConfig(
            input_data="{{upstream.data}}",  # Unresolved reference
            condition_field="status",
            condition_operator=ConditionalOperator.EQUALS,
            condition_value="active",
        )
    )

    node = ConditionalNode(
        node_id="conditional_26",
        node_type="conditional",
        node_data={},
        config=config,
    )

    with pytest.raises(ValueError) as exc_info:
        await node.execute({})

    assert "was not resolved" in str(exc_info.value)


@pytest.mark.asyncio
async def test_invalid_regex():
    """Test handling invalid regex pattern"""
    data = {"text": "hello world"}
    config = ConditionalNodeConfig(
        config=ConditionalInnerConfig(
            input_data=json.dumps(data),
            condition_field="text",
            condition_operator=ConditionalOperator.REGEX_MATCH,
            condition_value="[invalid(regex",  # Invalid regex
        )
    )

    node = ConditionalNode(
        node_id="conditional_27",
        node_type="conditional",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    # Invalid regex should return false, not crash
    assert result["condition_result"] is False


@pytest.mark.asyncio
async def test_missing_nested_field(sample_nested_data):
    """Test handling missing nested field"""
    config = ConditionalNodeConfig(
        config=ConditionalInnerConfig(
            input_data=json.dumps(sample_nested_data),
            condition_field="user.profile.nonexistent.field",
            condition_operator=ConditionalOperator.EQUALS,
            condition_value="test",
        )
    )

    node = ConditionalNode(
        node_id="conditional_28",
        node_type="conditional",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    # Missing field should be treated as None, equals "test" is false
    assert result["condition_result"] is False
    assert result["output_handle"] == "false"


@pytest.mark.asyncio
async def test_numeric_comparison_with_non_numeric():
    """Test numeric comparison with non-numeric values"""
    data = {"value": "not a number"}
    config = ConditionalNodeConfig(
        config=ConditionalInnerConfig(
            input_data=json.dumps(data),
            condition_field="value",
            condition_operator=ConditionalOperator.GREATER_THAN,
            condition_value="10",
        )
    )

    node = ConditionalNode(
        node_id="conditional_29",
        node_type="conditional",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    # Non-numeric comparison should return false, not crash
    assert result["condition_result"] is False


# ===== RESOLVED DATA TESTS =====

@pytest.mark.asyncio
async def test_with_resolved_list_data():
    """Test conditional with pre-resolved list data"""
    resolved_data = [
        {"name": "Item 1", "active": True},
        {"name": "Item 2", "active": False},
    ]

    config = ConditionalNodeConfig(
        config=ConditionalInnerConfig(
            input_data=resolved_data,  # Already resolved, not JSON string
            condition_field=None,  # Evaluate whole input
            condition_operator=ConditionalOperator.IS_NOT_EMPTY,
        )
    )

    node = ConditionalNode(
        node_id="conditional_30",
        node_type="conditional",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["condition_result"] is True
    assert result["output_handle"] == "true"
