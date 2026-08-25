"""
Tests for Merge node.
Verifies all 5 merge operations: append, combine_by_position, combine_by_field, keep_matches, remove_duplicates.
"""

import pytest
import json
from nodes.merge_node import (
    MergeNode,
    MergeNodeConfig,
)

# The merge config is a discriminated union over `operation` — passing a plain
# dict to MergeNodeConfig(config=...) routes to the correct operation variant,
# exactly as a saved workflow config loads.


# Test data fixtures
@pytest.fixture
def users_list_1():
    """First list of users"""
    return [
        {"id": 1, "name": "Alice", "email": "alice@example.com"},
        {"id": 2, "name": "Bob", "email": "bob@example.com"},
    ]


@pytest.fixture
def users_list_2():
    """Second list of users"""
    return [
        {"id": 3, "name": "Charlie", "email": "charlie@example.com"},
        {"id": 4, "name": "Diana", "email": "diana@example.com"},
    ]


@pytest.fixture
def users_with_extra_data():
    """Users with additional fields for combining"""
    return [
        {"id": 1, "department": "Engineering", "salary": 100000},
        {"id": 2, "department": "Marketing", "salary": 80000},
        {"id": 5, "department": "Sales", "salary": 75000},  # No match in users_list_1
    ]


@pytest.fixture
def names_list():
    """List of name objects"""
    return [
        {"name": "Alice"},
        {"name": "Bob"},
        {"name": "Charlie"},
    ]


@pytest.fixture
def ages_list():
    """List of age objects"""
    return [
        {"age": 30},
        {"age": 25},
        {"age": 35},
    ]


@pytest.fixture
def duplicate_emails():
    """List with duplicate emails"""
    return [
        {"id": 1, "email": "alice@example.com"},
        {"id": 2, "email": "bob@example.com"},
        {"id": 3, "email": "alice@example.com"},  # Duplicate
        {"id": 4, "email": "charlie@example.com"},
    ]


@pytest.fixture
def numbers_1():
    """First list of numbers"""
    return [1, 2, 3, 4, 5]


@pytest.fixture
def numbers_2():
    """Second list of numbers"""
    return [4, 5, 6, 7, 8]


# ===== APPEND OPERATION TESTS =====

@pytest.mark.asyncio
async def test_append_two_lists(users_list_1, users_list_2):
    """Test appending two lists"""
    config = MergeNodeConfig(
        config=dict(
            operation="append",
        )
    )

    node = MergeNode(
        node_id="merge_1",
        node_type="merge",
        node_data={},
        config=config,
    )

    # Simulate inputs from two predecessor nodes
    inputs = {
        "node_a": users_list_1,
        "node_b": users_list_2,
    }

    result = await node.execute(inputs)

    assert result["status"] == "success"
    assert result["operation"] == "append"
    assert result["count"] == 4
    assert result["input_count"] == 2
    assert len(result["merged"]) == 4
    assert result["merged"][0]["name"] == "Alice"
    assert result["merged"][3]["name"] == "Diana"


@pytest.mark.asyncio
async def test_append_three_lists(users_list_1, users_list_2):
    """Test appending three lists"""
    third_list = [{"id": 5, "name": "Eve", "email": "eve@example.com"}]

    config = MergeNodeConfig(
        config=dict(
            operation="append",
        )
    )

    node = MergeNode(
        node_id="merge_2",
        node_type="merge",
        node_data={},
        config=config,
    )

    inputs = {
        "node_a": users_list_1,
        "node_b": users_list_2,
        "node_c": third_list,
    }

    result = await node.execute(inputs)

    assert result["count"] == 5
    assert result["input_count"] == 3
    assert result["merged"][4]["name"] == "Eve"


@pytest.mark.asyncio
async def test_append_numbers(numbers_1, numbers_2):
    """Test appending number arrays"""
    config = MergeNodeConfig(
        config=dict(
            operation="append",
        )
    )

    node = MergeNode(
        node_id="merge_3",
        node_type="merge",
        node_data={},
        config=config,
    )

    inputs = {
        "node_a": numbers_1,
        "node_b": numbers_2,
    }

    result = await node.execute(inputs)

    assert result["count"] == 10
    assert result["merged"] == [1, 2, 3, 4, 5, 4, 5, 6, 7, 8]


@pytest.mark.asyncio
async def test_append_with_nested_data():
    """Test appending with data in nested structure"""
    config = MergeNodeConfig(
        config=dict(
            operation="append",
        )
    )

    node = MergeNode(
        node_id="merge_4",
        node_type="merge",
        node_data={},
        config=config,
    )

    # Data wrapped in typical API response structure
    inputs = {
        "api_1": {"data": [{"id": 1}, {"id": 2}], "status": "success"},
        "api_2": {"items": [{"id": 3}, {"id": 4}]},
    }

    result = await node.execute(inputs)

    assert result["count"] == 4
    assert result["merged"][0]["id"] == 1
    assert result["merged"][3]["id"] == 4


# ===== COMBINE BY POSITION TESTS =====

@pytest.mark.asyncio
async def test_combine_by_position(names_list, ages_list):
    """Test combining by position (zip)"""
    config = MergeNodeConfig(
        config=dict(
            operation="combine_by_position",
        )
    )

    node = MergeNode(
        node_id="merge_5",
        node_type="merge",
        node_data={},
        config=config,
    )

    inputs = {
        "names": names_list,
        "ages": ages_list,
    }

    result = await node.execute(inputs)

    assert result["status"] == "success"
    assert result["operation"] == "combine_by_position"
    assert result["count"] == 3
    assert result["merged"][0] == {"name": "Alice", "age": 30}
    assert result["merged"][1] == {"name": "Bob", "age": 25}
    assert result["merged"][2] == {"name": "Charlie", "age": 35}


@pytest.mark.asyncio
async def test_combine_by_position_unequal_lengths():
    """Test combining by position with unequal length arrays"""
    list_1 = [{"a": 1}, {"a": 2}, {"a": 3}]
    list_2 = [{"b": 10}, {"b": 20}]  # Shorter

    config = MergeNodeConfig(
        config=dict(
            operation="combine_by_position",
        )
    )

    node = MergeNode(
        node_id="merge_6",
        node_type="merge",
        node_data={},
        config=config,
    )

    inputs = {
        "list_1": list_1,
        "list_2": list_2,
    }

    result = await node.execute(inputs)

    # Should have 3 items (max length)
    assert result["count"] == 3
    assert result["merged"][0] == {"a": 1, "b": 10}
    assert result["merged"][1] == {"a": 2, "b": 20}
    assert result["merged"][2] == {"a": 3}  # No b value


@pytest.mark.asyncio
async def test_combine_by_position_with_primitives():
    """Test combining by position with non-object items"""
    list_1 = ["Alice", "Bob"]
    list_2 = [30, 25]

    config = MergeNodeConfig(
        config=dict(
            operation="combine_by_position",
        )
    )

    node = MergeNode(
        node_id="merge_7",
        node_type="merge",
        node_data={},
        config=config,
    )

    inputs = {
        "names": list_1,
        "ages": list_2,
    }

    result = await node.execute(inputs)

    assert result["count"] == 2
    # Non-dict items get input_N keys
    assert "input_0" in result["merged"][0] or "input_1" in result["merged"][0]


# ===== COMBINE BY FIELD TESTS =====

@pytest.mark.asyncio
async def test_combine_by_field(users_list_1, users_with_extra_data):
    """Test combining by matching field (join)"""
    config = MergeNodeConfig(
        config=dict(
            operation="combine_by_field",
            match_field="id",
            conflict_resolution="prefer_first",
        )
    )

    node = MergeNode(
        node_id="merge_8",
        node_type="merge",
        node_data={},
        config=config,
    )

    inputs = {
        "users": users_list_1,
        "extra": users_with_extra_data,
    }

    result = await node.execute(inputs)

    assert result["status"] == "success"
    assert result["operation"] == "combine_by_field"
    # Should have 3 unique IDs (1, 2 from both, 5 from extra only)
    assert result["count"] == 3

    # Find the merged record for id=1
    alice = next((r for r in result["merged"] if r["id"] == 1), None)
    assert alice is not None
    assert alice["name"] == "Alice"
    assert alice["department"] == "Engineering"


@pytest.mark.asyncio
async def test_combine_by_field_prefer_last():
    """Test combine by field with prefer_last conflict resolution"""
    list_1 = [{"id": 1, "value": "original"}]
    list_2 = [{"id": 1, "value": "updated"}]

    config = MergeNodeConfig(
        config=dict(
            operation="combine_by_field",
            match_field="id",
            conflict_resolution="prefer_last",
        )
    )

    node = MergeNode(
        node_id="merge_9",
        node_type="merge",
        node_data={},
        config=config,
    )

    inputs = {
        "list_1": list_1,
        "list_2": list_2,
    }

    result = await node.execute(inputs)

    assert result["merged"][0]["value"] == "updated"


@pytest.mark.asyncio
async def test_combine_by_field_merge_conflicts():
    """Test combine by field with merge conflict resolution"""
    list_1 = [{"id": 1, "tags": ["a", "b"]}]
    list_2 = [{"id": 1, "tags": ["c", "d"]}]

    config = MergeNodeConfig(
        config=dict(
            operation="combine_by_field",
            match_field="id",
            conflict_resolution="merge",
        )
    )

    node = MergeNode(
        node_id="merge_10",
        node_type="merge",
        node_data={},
        config=config,
    )

    inputs = {
        "list_1": list_1,
        "list_2": list_2,
    }

    result = await node.execute(inputs)

    # Merged lists should be concatenated
    assert result["merged"][0]["tags"] == ["a", "b", "c", "d"]


@pytest.mark.asyncio
async def test_combine_by_field_missing_match_field():
    """Test combine by field with missing match_field returns error"""
    config = MergeNodeConfig(
        config=dict(
            operation="combine_by_field",
            match_field=None,  # Missing
        )
    )

    node = MergeNode(
        node_id="merge_11",
        node_type="merge",
        node_data={},
        config=config,
    )

    inputs = {
        "list_1": [{"id": 1}],
        "list_2": [{"id": 2}],
    }

    result = await node.execute(inputs)

    assert result["status"] == "error"
    assert "match_field is required" in result["error"]


# ===== KEEP MATCHES TESTS =====

@pytest.mark.asyncio
async def test_keep_matches_with_field(numbers_1, numbers_2):
    """Test keep_matches (intersection) with simple values"""
    config = MergeNodeConfig(
        config=dict(
            operation="keep_matches",
        )
    )

    node = MergeNode(
        node_id="merge_12",
        node_type="merge",
        node_data={},
        config=config,
    )

    inputs = {
        "list_1": numbers_1,  # [1, 2, 3, 4, 5]
        "list_2": numbers_2,  # [4, 5, 6, 7, 8]
    }

    result = await node.execute(inputs)

    assert result["status"] == "success"
    assert result["operation"] == "keep_matches"
    # Only 4 and 5 are in both lists
    assert result["count"] == 2
    assert set(result["merged"]) == {4, 5}


@pytest.mark.asyncio
async def test_keep_matches_objects_by_field():
    """Test keep_matches with objects using match_field"""
    list_1 = [
        {"email": "alice@example.com", "name": "Alice"},
        {"email": "bob@example.com", "name": "Bob"},
        {"email": "charlie@example.com", "name": "Charlie"},
    ]
    list_2 = [
        {"email": "bob@example.com", "source": "api"},
        {"email": "charlie@example.com", "source": "api"},
        {"email": "diana@example.com", "source": "api"},
    ]

    config = MergeNodeConfig(
        config=dict(
            operation="keep_matches",
            match_field="email",
        )
    )

    node = MergeNode(
        node_id="merge_13",
        node_type="merge",
        node_data={},
        config=config,
    )

    inputs = {
        "list_1": list_1,
        "list_2": list_2,
    }

    result = await node.execute(inputs)

    assert result["count"] == 2
    emails = [r["email"] for r in result["merged"]]
    assert "bob@example.com" in emails
    assert "charlie@example.com" in emails
    assert "alice@example.com" not in emails


@pytest.mark.asyncio
async def test_keep_matches_no_overlap():
    """Test keep_matches when there's no overlap"""
    list_1 = [1, 2, 3]
    list_2 = [4, 5, 6]

    config = MergeNodeConfig(
        config=dict(
            operation="keep_matches",
        )
    )

    node = MergeNode(
        node_id="merge_14",
        node_type="merge",
        node_data={},
        config=config,
    )

    inputs = {
        "list_1": list_1,
        "list_2": list_2,
    }

    result = await node.execute(inputs)

    assert result["count"] == 0
    assert result["merged"] == []


# ===== REMOVE DUPLICATES TESTS =====

@pytest.mark.asyncio
async def test_remove_duplicates_simple(numbers_1, numbers_2):
    """Test remove_duplicates (union) with simple values"""
    config = MergeNodeConfig(
        config=dict(
            operation="remove_duplicates",
        )
    )

    node = MergeNode(
        node_id="merge_15",
        node_type="merge",
        node_data={},
        config=config,
    )

    inputs = {
        "list_1": numbers_1,  # [1, 2, 3, 4, 5]
        "list_2": numbers_2,  # [4, 5, 6, 7, 8]
    }

    result = await node.execute(inputs)

    assert result["status"] == "success"
    assert result["operation"] == "remove_duplicates"
    # Union: 1, 2, 3, 4, 5, 6, 7, 8
    assert result["count"] == 8
    assert set(result["merged"]) == {1, 2, 3, 4, 5, 6, 7, 8}


@pytest.mark.asyncio
async def test_remove_duplicates_by_field(duplicate_emails):
    """Test remove_duplicates with dedupe_field"""
    config = MergeNodeConfig(
        config=dict(
            operation="remove_duplicates",
            dedupe_field="email",
        )
    )

    node = MergeNode(
        node_id="merge_16",
        node_type="merge",
        node_data={},
        config=config,
    )

    inputs = {
        "list": duplicate_emails,
    }

    result = await node.execute(inputs)

    # 3 unique emails: alice, bob, charlie
    assert result["count"] == 3
    emails = [r["email"] for r in result["merged"]]
    assert len(set(emails)) == 3


@pytest.mark.asyncio
async def test_remove_duplicates_objects():
    """Test remove_duplicates with objects (entire object comparison)"""
    list_1 = [
        {"a": 1, "b": 2},
        {"a": 1, "b": 2},  # Duplicate
        {"a": 2, "b": 3},
    ]

    config = MergeNodeConfig(
        config=dict(
            operation="remove_duplicates",
        )
    )

    node = MergeNode(
        node_id="merge_17",
        node_type="merge",
        node_data={},
        config=config,
    )

    inputs = {
        "list": list_1,
    }

    result = await node.execute(inputs)

    assert result["count"] == 2


# ===== EDGE CASES AND ERROR HANDLING =====

@pytest.mark.asyncio
async def test_empty_inputs():
    """Test handling empty inputs"""
    config = MergeNodeConfig(
        config=dict(
            operation="append",
        )
    )

    node = MergeNode(
        node_id="merge_18",
        node_type="merge",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["status"] == "success"
    assert result["count"] == 0
    assert result["merged"] == []
    assert "No input data to merge" in result.get("message", "")


@pytest.mark.asyncio
async def test_single_input():
    """Test with only one input"""
    single_list = [{"id": 1}, {"id": 2}]

    config = MergeNodeConfig(
        config=dict(
            operation="append",
        )
    )

    node = MergeNode(
        node_id="merge_19",
        node_type="merge",
        node_data={},
        config=config,
    )

    inputs = {
        "only_one": single_list,
    }

    result = await node.execute(inputs)

    assert result["count"] == 2
    assert result["input_count"] == 1


@pytest.mark.asyncio
async def test_no_config():
    """Test handling missing config"""
    node = MergeNode(
        node_id="merge_20",
        node_type="merge",
        node_data={},
        config=None,
    )

    result = await node.execute({})

    assert result["status"] == "no_config"
    assert "Configuration required" in result["error"]


@pytest.mark.asyncio
async def test_null_inputs_ignored():
    """Test that null inputs are ignored"""
    config = MergeNodeConfig(
        config=dict(
            operation="append",
        )
    )

    node = MergeNode(
        node_id="merge_21",
        node_type="merge",
        node_data={},
        config=config,
    )

    inputs = {
        "valid": [{"id": 1}, {"id": 2}],
        "null_input": None,
    }

    result = await node.execute(inputs)

    assert result["count"] == 2
    assert result["input_count"] == 1  # Only valid input counted


@pytest.mark.asyncio
async def test_extract_from_filtered_output():
    """Test extracting arrays from filter node output structure"""
    config = MergeNodeConfig(
        config=dict(
            operation="append",
        )
    )

    node = MergeNode(
        node_id="merge_22",
        node_type="merge",
        node_data={},
        config=config,
    )

    # Simulating output from filter node
    inputs = {
        "filter_1": {
            "status": "success",
            "filtered": [{"id": 1}, {"id": 2}],
            "count": 2,
        },
        "filter_2": {
            "status": "success",
            "filtered": [{"id": 3}],
            "count": 1,
        },
    }

    result = await node.execute(inputs)

    assert result["count"] == 3
    assert result["merged"][0]["id"] == 1
    assert result["merged"][2]["id"] == 3


@pytest.mark.asyncio
async def test_extract_from_iteration_output():
    """Test extracting arrays from iteration node output"""
    config = MergeNodeConfig(
        config=dict(
            operation="append",
        )
    )

    node = MergeNode(
        node_id="merge_23",
        node_type="merge",
        node_data={},
        config=config,
    )

    # Simulating output from iteration node
    inputs = {
        "iteration_1": {
            "collected_results": [{"result": "a"}, {"result": "b"}],
            "total": 2,
            "completed": True,
        },
    }

    result = await node.execute(inputs)

    assert result["count"] == 2
    assert result["merged"][0]["result"] == "a"
