"""
Tests for Filter node.
Verifies all 5 filtering operations: filter_array, remove_duplicates, limit, sort, filter_object.
"""

import pytest
import json
from nodes.filter_node import (
    FilterNode,
    FilterNodeConfig,
    FilterArrayConfig,
    RemoveDuplicatesConfig,
    LimitConfig,
    SortConfig,
    FilterObjectConfig,
    GroupByFieldConfig,
    SplitStringConfig,
)



# Test data fixtures
@pytest.fixture
def sample_users():
    """Sample array of user objects"""
    return [
        {"name": "Alice", "age": 30, "city": "NYC", "status": "active"},
        {"name": "Bob", "age": 25, "city": "LA", "status": "inactive"},
        {"name": "Charlie", "age": 35, "city": "Chicago", "status": "active"},
        {"name": "Diana", "age": 28, "city": "NYC", "status": "active"},
        {"name": "Eve", "age": 40, "city": "Boston", "status": "inactive"},
    ]


@pytest.fixture
def sample_numbers():
    """Sample array of numbers"""
    return [10, 20, 30, 40, 50, 25, 15, 35]


@pytest.fixture
def sample_strings():
    """Sample array of strings"""
    return ["apple", "banana", "apricot", "cherry", "avocado"]


@pytest.fixture
def sample_duplicates():
    """Sample array with duplicates"""
    return [
        {"id": 1, "name": "Alice", "email": "alice@example.com"},
        {"id": 2, "name": "Bob", "email": "bob@example.com"},
        {"id": 3, "name": "Alice", "email": "alice@example.com"},  # Duplicate email
        {"id": 4, "name": "Charlie", "email": "charlie@example.com"},
        {"id": 5, "name": "Bob", "email": "bob2@example.com"},  # Different email
    ]


# ===== FILTER ARRAY TESTS =====

@pytest.mark.asyncio
async def test_filter_array_equals(sample_users):
    """Test filtering array with equals operator"""
    config = FilterNodeConfig(
        config=FilterArrayConfig(
            input_data=json.dumps(sample_users),
            filter_field="city",
            operator="equals",
            filter_value="NYC",
            case_sensitive="false",
        )
    )

    node = FilterNode(
        node_id="filter_1",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["operation"] == "filter_array"
    assert result["count"] == 2
    assert result["original_count"] == 5
    assert len(result["filtered"]) == 2
    assert result["filtered"][0]["name"] == "Alice"
    assert result["filtered"][1]["name"] == "Diana"


@pytest.mark.asyncio
async def test_filter_array_greater_than(sample_users):
    """Test filtering array with greater_than operator"""
    config = FilterNodeConfig(
        config=FilterArrayConfig(
            input_data=json.dumps(sample_users),
            filter_field="age",
            operator="greater_than",
            filter_value="30",
        )
    )

    node = FilterNode(
        node_id="filter_2",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["count"] == 2
    assert result["filtered"][0]["name"] == "Charlie"  # age 35
    assert result["filtered"][1]["name"] == "Eve"  # age 40


@pytest.mark.asyncio
async def test_filter_array_contains(sample_users):
    """Test filtering array with contains operator"""
    config = FilterNodeConfig(
        config=FilterArrayConfig(
            input_data=json.dumps(sample_users),
            filter_field="name",  # Changed from status to name to properly test CONTAINS
            operator="contains",
            filter_value="li",  # "li" is contained in "Alice" and "Charlie"
            case_sensitive="false",
        )
    )

    node = FilterNode(
        node_id="filter_3",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["count"] == 2  # Alice and Charlie
    assert result["filtered"][0]["name"] == "Alice"
    assert result["filtered"][1]["name"] == "Charlie"


@pytest.mark.asyncio
async def test_filter_array_starts_with(sample_strings):
    """Test filtering array with starts_with operator"""
    config = FilterNodeConfig(
        config=FilterArrayConfig(
            input_data=json.dumps(sample_strings),
            operator="starts_with",
            filter_value="a",
            case_sensitive="false",
        )
    )

    node = FilterNode(
        node_id="filter_4",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["count"] == 3
    assert set(result["filtered"]) == {"apple", "apricot", "avocado"}


@pytest.mark.asyncio
async def test_filter_array_in_list(sample_users):
    """Test filtering array with in_list operator"""
    config = FilterNodeConfig(
        config=FilterArrayConfig(
            input_data=json.dumps(sample_users),
            filter_field="city",
            operator="in_list",
            filter_value="NYC,Boston,LA",
        )
    )

    node = FilterNode(
        node_id="filter_5",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["count"] == 4
    cities = {user["city"] for user in result["filtered"]}
    assert cities == {"NYC", "Boston", "LA"}


@pytest.mark.asyncio
async def test_filter_array_is_empty(sample_users):
    """Test filtering array with is_empty operator"""
    # Add user with empty city
    users = sample_users + [{"name": "Frank", "age": 22, "city": "", "status": "active"}]

    config = FilterNodeConfig(
        config=FilterArrayConfig(
            input_data=json.dumps(users),
            filter_field="city",
            operator="is_empty",
        )
    )

    node = FilterNode(
        node_id="filter_6",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["count"] == 1
    assert result["filtered"][0]["name"] == "Frank"


@pytest.mark.asyncio
async def test_filter_array_regex_match():
    """Test filtering array with regex_match operator"""
    emails = ["alice@gmail.com", "bob@yahoo.com", "charlie@gmail.com", "diana@outlook.com"]

    config = FilterNodeConfig(
        config=FilterArrayConfig(
            input_data=json.dumps(emails),
            operator="regex_match",
            filter_value=".*@gmail\\.com$",
        )
    )

    node = FilterNode(
        node_id="filter_7",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["count"] == 2
    assert set(result["filtered"]) == {"alice@gmail.com", "charlie@gmail.com"}


@pytest.mark.asyncio
async def test_filter_array_direct_values(sample_numbers):
    """Test filtering array of direct values (no filter_field)"""
    config = FilterNodeConfig(
        config=FilterArrayConfig(
            input_data=json.dumps(sample_numbers),
            operator="greater_than",
            filter_value="25",
        )
    )

    node = FilterNode(
        node_id="filter_8",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["count"] == 4
    assert set(result["filtered"]) == {30, 40, 50, 35}


@pytest.mark.asyncio
async def test_filter_array_case_sensitive():
    """Test case sensitivity in filtering"""
    data = ["Apple", "BANANA", "apricot", "CHERRY"]

    # Case insensitive
    config_insensitive = FilterNodeConfig(
        config=FilterArrayConfig(
            input_data=json.dumps(data),
            operator="starts_with",
            filter_value="a",
            case_sensitive="false",
        )
    )

    node_insensitive = FilterNode(
        node_id="filter_9",
        node_type="filter",
        node_data={},
        config=config_insensitive,
    )

    result_insensitive = await node_insensitive.execute({})
    assert result_insensitive["count"] == 2  # Apple, apricot

    # Case sensitive
    config_sensitive = FilterNodeConfig(
        config=FilterArrayConfig(
            input_data=json.dumps(data),
            operator="starts_with",
            filter_value="a",
            case_sensitive="true",
        )
    )

    node_sensitive = FilterNode(
        node_id="filter_10",
        node_type="filter",
        node_data={},
        config=config_sensitive,
    )

    result_sensitive = await node_sensitive.execute({})
    assert result_sensitive["count"] == 1  # Only apricot


@pytest.mark.asyncio
async def test_case_sensitive_legacy_boolean_coercion():
    """Older filter nodes stored case_sensitive as a boolean — it must coerce to a string."""
    data = ["Apple", "apricot"]

    config = FilterNodeConfig(
        config=FilterArrayConfig(
            input_data=json.dumps(data),
            operator="starts_with",
            filter_value="a",
            case_sensitive=True,  # legacy boolean shape
        )
    )

    assert config.config.case_sensitive == "true"

    node = FilterNode(
        node_id="filter_legacy_cs",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})
    assert result["count"] == 1  # case sensitive — only "apricot"


# ===== ADDITIONAL OPERATOR COVERAGE =====

@pytest.mark.asyncio
async def test_filter_array_not_equals(sample_users):
    """Test filtering array with not_equals operator"""
    config = FilterNodeConfig(
        config=FilterArrayConfig(
            input_data=json.dumps(sample_users),
            filter_field="status",
            operator="not_equals",
            filter_value="active",
        )
    )
    node = FilterNode(node_id="op_1", node_type="filter", node_data={}, config=config)
    result = await node.execute({})
    assert result["count"] == 2  # Bob, Eve
    assert {u["name"] for u in result["filtered"]} == {"Bob", "Eve"}


@pytest.mark.asyncio
async def test_filter_array_not_contains(sample_users):
    """Test filtering array with not_contains operator"""
    config = FilterNodeConfig(
        config=FilterArrayConfig(
            input_data=json.dumps(sample_users),
            filter_field="name",
            operator="not_contains",
            filter_value="li",
        )
    )
    node = FilterNode(node_id="op_2", node_type="filter", node_data={}, config=config)
    result = await node.execute({})
    assert result["count"] == 3  # Bob, Diana, Eve
    assert {u["name"] for u in result["filtered"]} == {"Bob", "Diana", "Eve"}


@pytest.mark.asyncio
async def test_filter_array_ends_with(sample_strings):
    """Test filtering array with ends_with operator"""
    config = FilterNodeConfig(
        config=FilterArrayConfig(
            input_data=json.dumps(sample_strings),
            operator="ends_with",
            filter_value="a",
        )
    )
    node = FilterNode(node_id="op_3", node_type="filter", node_data={}, config=config)
    result = await node.execute({})
    assert result["filtered"] == ["banana"]


@pytest.mark.asyncio
async def test_filter_array_greater_than_or_equal(sample_users):
    """Test filtering array with greater_than_or_equal operator"""
    config = FilterNodeConfig(
        config=FilterArrayConfig(
            input_data=json.dumps(sample_users),
            filter_field="age",
            operator="greater_than_or_equal",
            filter_value="35",
        )
    )
    node = FilterNode(node_id="op_4", node_type="filter", node_data={}, config=config)
    result = await node.execute({})
    assert result["count"] == 2  # Charlie (35), Eve (40)


@pytest.mark.asyncio
async def test_filter_array_less_than(sample_users):
    """Test filtering array with less_than operator"""
    config = FilterNodeConfig(
        config=FilterArrayConfig(
            input_data=json.dumps(sample_users),
            filter_field="age",
            operator="less_than",
            filter_value="28",
        )
    )
    node = FilterNode(node_id="op_5", node_type="filter", node_data={}, config=config)
    result = await node.execute({})
    assert result["count"] == 1  # Bob (25)
    assert result["filtered"][0]["name"] == "Bob"


@pytest.mark.asyncio
async def test_filter_array_less_than_or_equal(sample_users):
    """Test filtering array with less_than_or_equal operator"""
    config = FilterNodeConfig(
        config=FilterArrayConfig(
            input_data=json.dumps(sample_users),
            filter_field="age",
            operator="less_than_or_equal",
            filter_value="28",
        )
    )
    node = FilterNode(node_id="op_6", node_type="filter", node_data={}, config=config)
    result = await node.execute({})
    assert result["count"] == 2  # Bob (25), Diana (28)


@pytest.mark.asyncio
async def test_filter_array_is_not_empty(sample_users):
    """Test filtering array with is_not_empty operator"""
    users = sample_users + [{"name": "Frank", "age": 22, "city": "", "status": "active"}]
    config = FilterNodeConfig(
        config=FilterArrayConfig(
            input_data=json.dumps(users),
            filter_field="city",
            operator="is_not_empty",
        )
    )
    node = FilterNode(node_id="op_7", node_type="filter", node_data={}, config=config)
    result = await node.execute({})
    assert result["count"] == 5  # everyone except Frank


@pytest.mark.asyncio
async def test_filter_array_not_in_list(sample_users):
    """Test filtering array with not_in_list operator"""
    config = FilterNodeConfig(
        config=FilterArrayConfig(
            input_data=json.dumps(sample_users),
            filter_field="city",
            operator="not_in_list",
            filter_value="NYC,LA",
        )
    )
    node = FilterNode(node_id="op_8", node_type="filter", node_data={}, config=config)
    result = await node.execute({})
    assert result["count"] == 2  # Charlie (Chicago), Eve (Boston)
    assert {u["city"] for u in result["filtered"]} == {"Chicago", "Boston"}


# ===== REMOVE DUPLICATES TESTS =====

@pytest.mark.asyncio
async def test_remove_duplicates_by_field(sample_duplicates):
    """Test removing duplicates based on a specific field"""
    config = FilterNodeConfig(
        config=RemoveDuplicatesConfig(
            input_data=json.dumps(sample_duplicates),
            dedupe_field="email",
        )
    )

    node = FilterNode(
        node_id="filter_11",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["operation"] == "remove_duplicates"
    assert result["count"] == 4  # One duplicate removed
    assert result["duplicates_removed"] == 1
    emails = {item["email"] for item in result["filtered"]}
    assert len(emails) == 4


@pytest.mark.asyncio
async def test_remove_duplicates_entire_objects():
    """Test removing duplicate entire objects"""
    data = [
        {"name": "Alice", "age": 30},
        {"name": "Bob", "age": 25},
        {"name": "Alice", "age": 30},  # Exact duplicate
        {"name": "Charlie", "age": 35},
    ]

    config = FilterNodeConfig(
        config=RemoveDuplicatesConfig(
            input_data=json.dumps(data),
        )
    )

    node = FilterNode(
        node_id="filter_12",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["count"] == 3
    assert result["duplicates_removed"] == 1


@pytest.mark.asyncio
async def test_remove_duplicates_primitives():
    """Test removing duplicates from array of primitives"""
    data = [1, 2, 3, 2, 4, 1, 5, 3]

    config = FilterNodeConfig(
        config=RemoveDuplicatesConfig(
            input_data=json.dumps(data),
        )
    )

    node = FilterNode(
        node_id="filter_13",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["count"] == 5
    assert set(result["filtered"]) == {1, 2, 3, 4, 5}
    assert result["duplicates_removed"] == 3


# ===== LIMIT TESTS =====

@pytest.mark.asyncio
async def test_limit_basic(sample_users):
    """Test limiting array to first N items"""
    config = FilterNodeConfig(
        config=LimitConfig(
            input_data=json.dumps(sample_users),
            limit=3,
        )
    )

    node = FilterNode(
        node_id="filter_14",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["operation"] == "limit"
    assert result["count"] == 3
    assert result["limit"] == 3
    assert result["offset"] == 0
    assert len(result["filtered"]) == 3
    assert result["filtered"][0]["name"] == "Alice"


@pytest.mark.asyncio
async def test_limit_with_offset(sample_users):
    """Test limiting array with offset (pagination)"""
    config = FilterNodeConfig(
        config=LimitConfig(
            input_data=json.dumps(sample_users),
            limit=2,
            offset=2,
        )
    )

    node = FilterNode(
        node_id="filter_15",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["count"] == 2
    assert result["limit"] == 2
    assert result["offset"] == 2
    assert result["filtered"][0]["name"] == "Charlie"
    assert result["filtered"][1]["name"] == "Diana"


@pytest.mark.asyncio
async def test_limit_exceeds_array_length(sample_users):
    """Test limit larger than array length"""
    config = FilterNodeConfig(
        config=LimitConfig(
            input_data=json.dumps(sample_users),
            limit=100,
        )
    )

    node = FilterNode(
        node_id="filter_16",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["count"] == 5  # All items
    assert len(result["filtered"]) == 5


@pytest.mark.asyncio
async def test_limit_legacy_null_coercion(sample_users):
    """Older filter nodes could store limit as null before it was required."""
    config = FilterNodeConfig(
        config=LimitConfig(
            input_data=json.dumps(sample_users),
            limit=None,  # legacy null shape
        )
    )

    assert config.config.limit == 10

    node = FilterNode(
        node_id="filter_limit_null",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})
    assert result["count"] == 5  # all 5 users, limit 10 exceeds length


# ===== SORT TESTS =====

@pytest.mark.asyncio
async def test_sort_ascending(sample_users):
    """Test sorting array in ascending order"""
    config = FilterNodeConfig(
        config=SortConfig(
            input_data=json.dumps(sample_users),
            sort_field="age",
            sort_order="ascending",
        )
    )

    node = FilterNode(
        node_id="filter_17",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["operation"] == "sort"
    assert result["sort_field"] == "age"
    assert result["sort_order"] == "ascending"
    ages = [user["age"] for user in result["filtered"]]
    assert ages == [25, 28, 30, 35, 40]


@pytest.mark.asyncio
async def test_sort_descending(sample_users):
    """Test sorting array in descending order"""
    config = FilterNodeConfig(
        config=SortConfig(
            input_data=json.dumps(sample_users),
            sort_field="name",
            sort_order="descending",
        )
    )

    node = FilterNode(
        node_id="filter_18",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    names = [user["name"] for user in result["filtered"]]
    assert names == ["Eve", "Diana", "Charlie", "Bob", "Alice"]


@pytest.mark.asyncio
async def test_sort_direct_values(sample_numbers):
    """Test sorting array of direct values"""
    config = FilterNodeConfig(
        config=SortConfig(
            input_data=json.dumps(sample_numbers),
            sort_order="ascending",
        )
    )

    node = FilterNode(
        node_id="filter_19",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["filtered"] == [10, 15, 20, 25, 30, 35, 40, 50]


@pytest.mark.asyncio
async def test_sort_strings(sample_strings):
    """Test sorting array of strings"""
    config = FilterNodeConfig(
        config=SortConfig(
            input_data=json.dumps(sample_strings),
            sort_order="ascending",
        )
    )

    node = FilterNode(
        node_id="filter_20",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["filtered"] == ["apple", "apricot", "avocado", "banana", "cherry"]


# ===== FILTER OBJECT TESTS =====

@pytest.mark.asyncio
async def test_filter_object_keep_keys():
    """Test filtering object to keep only specified keys"""
    data = {
        "name": "Alice",
        "age": 30,
        "email": "alice@example.com",
        "password": "secret123",
        "internal_id": "xyz789",
        "city": "NYC",
    }

    config = FilterNodeConfig(
        config=FilterObjectConfig(
            input_data=json.dumps(data),
            keep_keys="name,email,city",
        )
    )

    node = FilterNode(
        node_id="filter_21",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["operation"] == "filter_object"
    assert result["keys_count"] == 3
    assert set(result["filtered"].keys()) == {"name", "email", "city"}
    assert result["filtered"]["name"] == "Alice"
    assert "password" not in result["filtered"]
    assert "internal_id" not in result["filtered"]


@pytest.mark.asyncio
async def test_filter_object_remove_keys():
    """Test filtering object to remove specified keys"""
    data = {
        "name": "Alice",
        "age": 30,
        "email": "alice@example.com",
        "password": "secret123",
        "internal_id": "xyz789",
    }

    config = FilterNodeConfig(
        config=FilterObjectConfig(
            input_data=json.dumps(data),
            remove_keys="password,internal_id",
        )
    )

    node = FilterNode(
        node_id="filter_22",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["keys_count"] == 3
    assert set(result["filtered"].keys()) == {"name", "age", "email"}
    assert "password" not in result["filtered"]
    assert "internal_id" not in result["filtered"]


@pytest.mark.asyncio
async def test_filter_object_keep_keys_priority():
    """Test that keep_keys takes priority over remove_keys"""
    data = {
        "name": "Alice",
        "age": 30,
        "email": "alice@example.com",
        "password": "secret123",
    }

    config = FilterNodeConfig(
        config=FilterObjectConfig(
            input_data=json.dumps(data),
            keep_keys="name,age",
            remove_keys="password",  # Should be ignored since keep_keys is specified
        )
    )

    node = FilterNode(
        node_id="filter_23",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert set(result["filtered"].keys()) == {"name", "age"}


# ===== GROUP BY FIELD TESTS =====

@pytest.mark.asyncio
async def test_group_by_field():
    """Test grouping array items into buckets by a field value"""
    data = [
        {"type": "a", "v": 1},
        {"type": "b", "v": 2},
        {"type": "a", "v": 3},
    ]
    config = FilterNodeConfig(
        config=GroupByFieldConfig(
            input_data=json.dumps(data),
            group_by_field="type",
        )
    )
    node = FilterNode(node_id="grp_1", node_type="filter", node_data={}, config=config)
    result = await node.execute({})

    assert result["operation"] == "group_by_field"
    assert result["status"] == "success"
    assert set(result["filtered"].keys()) == {"a", "b"}
    assert len(result["filtered"]["a"]) == 2
    assert len(result["filtered"]["b"]) == 1
    assert result["count"] == 2
    assert result["total_items"] == 3


@pytest.mark.asyncio
async def test_group_by_field_missing_field():
    """Test that group_by_field requires the field name"""
    config = FilterNodeConfig(
        config=GroupByFieldConfig(input_data=json.dumps([{"a": 1}]))
    )
    node = FilterNode(node_id="grp_2", node_type="filter", node_data={}, config=config)
    result = await node.execute({})

    assert result["status"] == "error"
    assert "group_by_field" in result["error"]


# ===== SPLIT STRING TESTS =====

@pytest.mark.asyncio
async def test_split_string():
    """Test splitting a string into an array by a delimiter"""
    config = FilterNodeConfig(
        config=SplitStringConfig(
            input_data="apple, banana , cherry",
            delimiter=",",
            trim_whitespace="true",
        )
    )
    node = FilterNode(node_id="ss_1", node_type="filter", node_data={}, config=config)
    result = await node.execute({})

    assert result["operation"] == "split_string"
    assert result["status"] == "success"
    assert result["filtered"] == ["apple", "banana", "cherry"]
    assert result["count"] == 3


@pytest.mark.asyncio
async def test_split_string_no_trim():
    """Test splitting a string without trimming whitespace"""
    config = FilterNodeConfig(
        config=SplitStringConfig(
            input_data="a | b | c",
            delimiter="|",
            trim_whitespace="false",
        )
    )
    node = FilterNode(node_id="ss_2", node_type="filter", node_data={}, config=config)
    result = await node.execute({})

    assert result["filtered"] == ["a ", " b ", " c"]


@pytest.mark.asyncio
async def test_split_string_legacy_boolean_coercion():
    """Older split nodes stored trim_whitespace as a boolean."""
    config = FilterNodeConfig(
        config=SplitStringConfig(
            input_data="x , y",
            delimiter=",",
            trim_whitespace=True,  # legacy boolean shape
        )
    )
    assert config.config.trim_whitespace == "true"

    node = FilterNode(node_id="ss_3", node_type="filter", node_data={}, config=config)
    result = await node.execute({})
    assert result["filtered"] == ["x", "y"]


# ===== DISCRIMINATOR ROUTING =====

@pytest.mark.asyncio
async def test_config_routes_by_operation():
    """A plain dict config routes to the correct variant via the operation discriminator."""
    config = FilterNodeConfig(
        config={
            "operation": "sort",
            "input_data": "[3, 1, 2]",
            "sort_order": "descending",
        }
    )
    assert isinstance(config.config, SortConfig)

    node = FilterNode(
        node_id="filter_discrim",
        node_type="filter",
        node_data={},
        config=config,
    )
    result = await node.execute({})
    assert result["operation"] == "sort"
    assert result["filtered"] == [3, 2, 1]


# ===== ERROR HANDLING TESTS =====

@pytest.mark.asyncio
async def test_no_config():
    """Test handling missing config"""
    node = FilterNode(
        node_id="filter_24",
        node_type="filter",
        node_data={},
        config=None,
    )

    result = await node.execute({})

    assert result["status"] == "no_config"


@pytest.mark.asyncio
async def test_invalid_json():
    """Test handling invalid JSON input"""
    config = FilterNodeConfig(
        config=FilterArrayConfig(
            input_data="not valid json",
            operator="equals",
            filter_value="test",
        )
    )

    node = FilterNode(
        node_id="filter_25",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["status"] == "error"
    assert "error" in result


@pytest.mark.asyncio
async def test_invalid_regex():
    """Test handling invalid regex pattern"""
    config = FilterNodeConfig(
        config=FilterArrayConfig(
            input_data='["test"]',
            operator="regex_match",
            filter_value="[invalid(regex",  # Invalid regex
        )
    )

    node = FilterNode(
        node_id="filter_26",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["status"] == "error"
    assert "error" in result


@pytest.mark.asyncio
async def test_filter_object_on_array():
    """Test using filter_object on array should return error"""
    config = FilterNodeConfig(
        config=FilterObjectConfig(
            input_data='[{"name": "Alice"}]',  # Array instead of object
            keep_keys="name",
        )
    )

    node = FilterNode(
        node_id="filter_27",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["status"] == "error"
    assert "must be an object" in result["error"].lower()


@pytest.mark.asyncio
async def test_empty_array():
    """Test filtering empty array"""
    config = FilterNodeConfig(
        config=FilterArrayConfig(
            input_data="[]",
            operator="equals",
            filter_value="test",
        )
    )

    node = FilterNode(
        node_id="filter_28",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["status"] == "success"
    assert result["count"] == 0
    assert result["filtered"] == []


@pytest.mark.asyncio
async def test_empty_object():
    """Test filtering empty object"""
    config = FilterNodeConfig(
        config=FilterObjectConfig(
            input_data="{}",
            keep_keys="name",
        )
    )

    node = FilterNode(
        node_id="filter_29",
        node_type="filter",
        node_data={},
        config=config,
    )

    result = await node.execute({})

    assert result["status"] == "success"
    assert result["keys_count"] == 0
    assert result["filtered"] == {}
