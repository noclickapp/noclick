"""
Tests for Switch node.
Verifies multi-way branching operations based on value matching.
"""

import pytest
import json
from nodes.switch_node import (
    SwitchNode,
    SwitchNodeConfig,
    SwitchInnerConfig,
    SwitchCase,
)


# Test data fixtures
@pytest.fixture
def sample_order():
    """Sample order object for switch testing"""
    return {
        "id": 12345,
        "status": "pending",
        "category": "electronics",
        "priority": "high",
        "amount": 299.99,
    }


# ===== SWITCH OPERATION TESTS =====

@pytest.mark.asyncio
async def test_switch_match_first_case():
    """Test switch with matching first case"""
    config = SwitchNodeConfig(
        config=SwitchInnerConfig(
            input_data="pending",  # Direct value to match
            switch_cases=[
                SwitchCase(value="pending"),
                SwitchCase(value="completed"),
                SwitchCase(value="cancelled"),
            ],
            default_output="unknown",
            case_sensitive="false",
        )
    )

    node = SwitchNode(
        node_id="switch_1",
        node_type="switch",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["status"] == "success"
    assert result["operation"] == "switch"
    assert result["output_handle"] == "pending"
    assert result["matched_case"] == "pending"
    assert "pending" in result["available_cases"]


@pytest.mark.asyncio
async def test_switch_match_middle_case():
    """Test switch with matching middle case"""
    config = SwitchNodeConfig(
        config=SwitchInnerConfig(
            input_data="completed",  # Direct value to match
            switch_cases=[
                SwitchCase(value="pending"),
                SwitchCase(value="completed"),
                SwitchCase(value="cancelled"),
            ],
            default_output="unknown",
            case_sensitive="false",
        )
    )

    node = SwitchNode(
        node_id="switch_2",
        node_type="switch",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["output_handle"] == "completed"
    assert result["matched_case"] == "completed"


@pytest.mark.asyncio
async def test_switch_no_match_uses_default():
    """Test switch with no matching case - uses default"""
    config = SwitchNodeConfig(
        config=SwitchInnerConfig(
            input_data="processing",  # Value not in cases
            switch_cases=[
                SwitchCase(value="pending"),
                SwitchCase(value="completed"),
                SwitchCase(value="cancelled"),
            ],
            default_output="unknown",
            case_sensitive="false",
        )
    )

    node = SwitchNode(
        node_id="switch_3",
        node_type="switch",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["output_handle"] == "unknown"
    assert result["matched_case"] is None


@pytest.mark.asyncio
async def test_switch_case_insensitive():
    """Test switch with case insensitive matching"""
    config = SwitchNodeConfig(
        config=SwitchInnerConfig(
            input_data="PENDING",  # Uppercase
            switch_cases=[
                SwitchCase(value="pending"),
                SwitchCase(value="completed"),
            ],
            default_output="default",
            case_sensitive="false",
        )
    )

    node = SwitchNode(
        node_id="switch_4",
        node_type="switch",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["output_handle"] == "pending"
    assert result["matched_case"] == "pending"


@pytest.mark.asyncio
async def test_switch_case_sensitive():
    """Test switch with case sensitive matching"""
    config = SwitchNodeConfig(
        config=SwitchInnerConfig(
            input_data="PENDING",  # Uppercase
            switch_cases=[
                SwitchCase(value="pending"),  # lowercase
                SwitchCase(value="PENDING"),  # uppercase
            ],
            default_output="default",
            case_sensitive="true",
        )
    )

    node = SwitchNode(
        node_id="switch_5",
        node_type="switch",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["output_handle"] == "PENDING"
    assert result["matched_case"] == "PENDING"


@pytest.mark.asyncio
async def test_switch_by_category():
    """Test switch on category field"""
    config = SwitchNodeConfig(
        config=SwitchInnerConfig(
            input_data="electronics",
            switch_cases=[
                SwitchCase(value="electronics"),
                SwitchCase(value="clothing"),
                SwitchCase(value="food"),
            ],
            default_output="general",
            case_sensitive="false",
        )
    )

    node = SwitchNode(
        node_id="switch_6",
        node_type="switch",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["output_handle"] == "electronics"
    assert result["matched_case"] == "electronics"
    assert "electronics" in result["available_cases"]


@pytest.mark.asyncio
async def test_switch_preserves_data():
    """Test that switch preserves original data in output"""
    config = SwitchNodeConfig(
        config=SwitchInnerConfig(
            input_data="high",
            switch_cases=[
                SwitchCase(value="high"),
                SwitchCase(value="medium"),
                SwitchCase(value="low"),
            ],
            default_output="default",
            case_sensitive="false",
        )
    )

    node = SwitchNode(
        node_id="switch_7",
        node_type="switch",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["output_handle"] == "high"
    assert result["data"] == "high"


@pytest.mark.asyncio
async def test_switch_with_json_input(sample_order):
    """Test switch with JSON string input for extracted field value"""
    config = SwitchNodeConfig(
        config=SwitchInnerConfig(
            input_data=json.dumps("pending"),  # JSON-encoded value
            switch_cases=[
                SwitchCase(value="pending"),
                SwitchCase(value="completed"),
            ],
            default_output="default",
            case_sensitive="false",
        )
    )

    node = SwitchNode(
        node_id="switch_8",
        node_type="switch",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["output_handle"] == "pending"


@pytest.mark.asyncio
async def test_switch_with_numeric_value():
    """Test switch with numeric value"""
    config = SwitchNodeConfig(
        config=SwitchInnerConfig(
            input_data=1,  # Numeric value
            switch_cases=[
                SwitchCase(value="1"),
                SwitchCase(value="2"),
                SwitchCase(value="3"),
            ],
            default_output="other",
            case_sensitive="false",
        )
    )

    node = SwitchNode(
        node_id="switch_9",
        node_type="switch",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["output_handle"] == "1"
    assert result["matched_case"] == "1"


# ===== ERROR HANDLING TESTS =====

@pytest.mark.asyncio
async def test_switch_no_config():
    """Test handling missing config"""
    node = SwitchNode(
        node_id="switch_10",
        node_type="switch",
        node_data={},
        config=None,
    )

    with pytest.raises(ValueError) as exc_info:
        await node.execute({})

    assert "Configuration required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_switch_unresolved_reference():
    """Test handling unresolved reference"""
    config = SwitchNodeConfig(
        config=SwitchInnerConfig(
            input_data="{{upstream.data}}",  # Unresolved reference
            switch_cases=[
                SwitchCase(value="pending"),
                SwitchCase(value="completed"),
            ],
            default_output="default",
            case_sensitive="false",
        )
    )

    node = SwitchNode(
        node_id="switch_11",
        node_type="switch",
        node_data={},
        config=config,
    )

    with pytest.raises(ValueError) as exc_info:
        await node.execute({})

    assert "was not resolved" in str(exc_info.value)


@pytest.mark.asyncio
async def test_switch_empty_cases():
    """Test switch with no cases defined"""
    config = SwitchNodeConfig(
        config=SwitchInnerConfig(
            input_data="pending",
            switch_cases=[],  # No cases
            default_output="fallback",
            case_sensitive="false",
        )
    )

    node = SwitchNode(
        node_id="switch_12",
        node_type="switch",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    # Should route to default when no cases match
    assert result["output_handle"] == "fallback"
    assert result["matched_case"] is None


@pytest.mark.asyncio
async def test_switch_none_cases():
    """Test switch with None cases"""
    config = SwitchNodeConfig(
        config=SwitchInnerConfig(
            input_data="pending",
            switch_cases=None,  # No cases
            default_output="fallback",
            case_sensitive="false",
        )
    )

    node = SwitchNode(
        node_id="switch_13",
        node_type="switch",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    # Should route to default when no cases provided
    assert result["output_handle"] == "fallback"
    assert result["matched_case"] is None


@pytest.mark.asyncio
async def test_switch_no_default():
    """Test switch with no default output specified"""
    config = SwitchNodeConfig(
        config=SwitchInnerConfig(
            input_data="unknown_value",
            switch_cases=[
                SwitchCase(value="pending"),
                SwitchCase(value="completed"),
            ],
            default_output=None,  # No default
            case_sensitive="false",
        )
    )

    node = SwitchNode(
        node_id="switch_14",
        node_type="switch",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    # Should route to "default" when no default_output specified
    assert result["output_handle"] == "default"
    assert result["matched_case"] is None
