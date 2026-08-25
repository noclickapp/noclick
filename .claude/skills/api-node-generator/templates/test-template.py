#!/usr/bin/env python3
"""
Integration tests for {SERVICE_NAME} REST API node.

Tests all operations against the live {SERVICE_NAME} API using real credentials.
Designed to be non-destructive where possible (read operations) and clean up
after write operations.

Usage:
    python scripts/test_{service_name}_integration.py <API_KEY>
    # or
    {SERVICE_UPPER}_API_KEY=<key> python scripts/test_{service_name}_integration.py

Documentation: {DOCS_URL}
"""

import asyncio
import sys
import os
import time

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nodes.{service_name}_node import (
    {ServiceName}Node,
    {ServiceName}NodeConfig,
    {ServiceName}Credential,
    # Import all config classes for testing
    {ServiceName}List{Resource}Config,
    {ServiceName}Get{Resource}Config,
    {ServiceName}Create{Resource}Config,
    {ServiceName}Update{Resource}Config,
    {ServiceName}Delete{Resource}Config,
    # ... more configs
)


# ============================================================================
# Test Constants
# ============================================================================

# Use existing resources for read-only tests (if applicable)
TEST_{RESOURCE}_ID = "test-id"  # Replace with a real test ID or create in setUp


class TestRunner:
    """
    Test runner for {SERVICE_NAME} node integration tests.

    Manages test execution, result tracking, and reporting.
    """

    def __init__(self, api_key: str):
        """Initialize with API credentials."""
        self.credentials = {ServiceName}Credential(api_key=api_key)
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        # Track created resources for cleanup
        self.created_resources = []

    def create_node(self, config) -> {ServiceName}Node:
        """Create a node instance with the given config."""
        node_config = {ServiceName}NodeConfig(
            config=config,
            credentials=self.credentials
        )
        return {ServiceName}Node(
            node_id="test-node",
            node_type="automation-{service-name}",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow"
        )

    async def run_test(self, name: str, test_func):
        """Run a single test and track results."""
        try:
            await test_func()
            print(f"  PASS: {name}")
            self.passed += 1
        except AssertionError as e:
            print(f"  FAIL: {name} - {e}")
            self.failed += 1
        except Exception as e:
            print(f"  ERROR: {name} - {type(e).__name__}: {e}")
            self.failed += 1

    def skip_test(self, name: str, reason: str):
        """Skip a test with a reason."""
        print(f"  SKIP: {name} - {reason}")
        self.skipped += 1

    async def cleanup(self):
        """Clean up any resources created during testing."""
        print("\n[Cleanup]")
        for resource_type, resource_id in self.created_resources:
            try:
                print(f"  Cleaning up {resource_type}: {resource_id}")
                # Add cleanup logic here
                # await self._delete_resource(resource_type, resource_id)
            except Exception as e:
                print(f"  Warning: Failed to clean up {resource_type} {resource_id}: {e}")

    async def run_all_tests(self):
        """Run all test categories."""
        print("\n" + "=" * 70)
        print("{SERVICE_NAME} Node Integration Tests")
        print("=" * 70)
        print(f"API Base: {SERVICE_UPPER}_API_BASE")
        print("=" * 70 + "\n")

        try:
            # =============================================
            # {Category1} Tests
            # =============================================
            print("\n[{Category1} Operations]")
            await self.run_test("list_{resources}", self.test_list_{resources})
            await self.run_test("get_{resource}", self.test_get_{resource})
            await self.run_test("create_{resource}", self.test_create_{resource})
            await self.run_test("update_{resource}", self.test_update_{resource})
            await self.run_test("delete_{resource}", self.test_delete_{resource})

            # =============================================
            # {Category2} Tests
            # =============================================
            print("\n[{Category2} Operations]")
            # await self.run_test("...", self.test_...)

            # =============================================
            # Error Handling Tests
            # =============================================
            print("\n[Error Handling]")
            await self.run_test("invalid_resource_id", self.test_invalid_resource_id)
            await self.run_test("missing_required_field", self.test_missing_required_field)

            # =============================================
            # Performance Tests
            # =============================================
            print("\n[Performance]")
            await self.run_test("timing_information", self.test_timing_information)

        finally:
            # Always run cleanup
            await self.cleanup()

        # Print summary
        print("\n" + "=" * 70)
        total = self.passed + self.failed + self.skipped
        print(f"Results: {self.passed} passed, {self.failed} failed, {self.skipped} skipped (total: {total})")
        print("=" * 70 + "\n")

        return self.failed == 0

    # =========================================================================
    # {Category1} Test Methods
    # =========================================================================

    async def test_list_{resources}(self):
        """Test listing {resources}."""
        config = {ServiceName}List{Resource}Config(
            page=1,
            per_page=5
        )
        node = self.create_node(config)
        result = await node.execute({})

        assert result["status"] == "success", f"Expected success, got {result['status']}: {result.get('error', '')}"
        assert result["action"] == "list_{resources}"
        assert isinstance(result["data"], (list, dict)), "Expected list or dict response"

    async def test_get_{resource}(self):
        """Test getting a specific {resource}."""
        # First list to get a valid ID
        list_config = {ServiceName}List{Resource}Config(per_page=1)
        list_node = self.create_node(list_config)
        list_result = await list_node.execute({})

        if list_result["status"] != "success" or not list_result.get("data"):
            self.skip_test("get_{resource}", "No {resources} available for testing")
            return

        # Get the first {resource}
        {resource}_id = list_result["data"][0].get("id")  # Adjust based on API response structure

        config = {ServiceName}Get{Resource}Config({resource}_id={resource}_id)
        node = self.create_node(config)
        result = await node.execute({})

        assert result["status"] == "success", f"Expected success, got {result['status']}"
        assert result["action"] == "get_{resource}"

    async def test_create_{resource}(self):
        """Test creating a {resource}."""
        config = {ServiceName}Create{Resource}Config(
            name=f"Test {Resource} {int(time.time())}",
            description="Created by integration test"
        )
        node = self.create_node(config)
        result = await node.execute({})

        assert result["status"] == "success", f"Expected success, got {result['status']}: {result.get('error', '')}"
        assert result["action"] == "create_{resource}"

        # Track for cleanup
        if result.get("data", {}).get("id"):
            self.created_resources.append(("{resource}", result["data"]["id"]))

    async def test_update_{resource}(self):
        """Test updating a {resource}."""
        # First create a {resource} to update
        create_config = {ServiceName}Create{Resource}Config(
            name=f"Test {Resource} to Update {int(time.time())}",
            description="Will be updated"
        )
        create_node = self.create_node(create_config)
        create_result = await create_node.execute({})

        if create_result["status"] != "success":
            self.skip_test("update_{resource}", "Could not create {resource} for update test")
            return

        {resource}_id = create_result["data"]["id"]
        self.created_resources.append(("{resource}", {resource}_id))

        # Now update it
        config = {ServiceName}Update{Resource}Config(
            {resource}_id={resource}_id,
            name=f"Updated {Resource} {int(time.time())}",
            description="Updated by integration test"
        )
        node = self.create_node(config)
        result = await node.execute({})

        assert result["status"] == "success", f"Expected success, got {result['status']}"
        assert result["action"] == "update_{resource}"

    async def test_delete_{resource}(self):
        """Test deleting a {resource}."""
        # First create a {resource} to delete
        create_config = {ServiceName}Create{Resource}Config(
            name=f"Test {Resource} to Delete {int(time.time())}",
            description="Will be deleted"
        )
        create_node = self.create_node(create_config)
        create_result = await create_node.execute({})

        if create_result["status"] != "success":
            self.skip_test("delete_{resource}", "Could not create {resource} for delete test")
            return

        {resource}_id = create_result["data"]["id"]

        # Delete it
        config = {ServiceName}Delete{Resource}Config({resource}_id={resource}_id)
        node = self.create_node(config)
        result = await node.execute({})

        assert result["status"] == "success", f"Expected success, got {result['status']}"
        assert result["action"] == "delete_{resource}"

    # =========================================================================
    # Error Handling Test Methods
    # =========================================================================

    async def test_invalid_resource_id(self):
        """Test handling of invalid resource ID."""
        config = {ServiceName}Get{Resource}Config(
            {resource}_id="invalid-nonexistent-id-12345"
        )
        node = self.create_node(config)
        result = await node.execute({})

        assert result["status"] == "error", "Expected error for invalid ID"
        assert result["status_code"] in [404, 400], f"Expected 404 or 400, got {result['status_code']}"

    async def test_missing_required_field(self):
        """Test validation of required fields."""
        # This test verifies Pydantic validation works
        try:
            config = {ServiceName}Create{Resource}Config(
                # Missing required 'name' field
                description="Test without name"
            )
            # Should raise validation error before we get here
            assert False, "Expected validation error for missing required field"
        except Exception as e:
            # Pydantic validation should catch this
            assert "name" in str(e).lower() or "required" in str(e).lower()

    # =========================================================================
    # Performance Test Methods
    # =========================================================================

    async def test_timing_information(self):
        """Test that timing information is included in responses."""
        config = {ServiceName}List{Resource}Config(per_page=1)
        node = self.create_node(config)
        result = await node.execute({})

        assert "timing_ms" in result, "Response should include timing_ms"
        assert "api_request" in result["timing_ms"], "timing_ms should include api_request"
        assert "total" in result["timing_ms"], "timing_ms should include total"
        assert result["timing_ms"]["api_request"] > 0, "API request time should be positive"
        assert result["timing_ms"]["total"] > 0, "Total time should be positive"
        assert result["timing_ms"]["total"] >= result["timing_ms"]["api_request"], \
            "Total time should be >= API request time"


# ============================================================================
# Main Entry Point
# ============================================================================

async def main():
    """Main entry point for running tests."""
    # Get API key from environment or command line
    api_key = os.environ.get("{SERVICE_UPPER}_API_KEY", "")

    if len(sys.argv) > 1:
        api_key = sys.argv[1]

    if not api_key:
        print("ERROR: API key required.")
        print()
        print("Usage:")
        print(f"  python scripts/test_{service_name}_integration.py <API_KEY>")
        print("  # or")
        print(f"  {SERVICE_UPPER}_API_KEY=<key> python scripts/test_{service_name}_integration.py")
        print()
        print("Get your API key at: {CREDENTIAL_URL}")
        sys.exit(1)

    runner = TestRunner(api_key)
    success = await runner.run_all_tests()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
