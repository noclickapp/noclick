"""
Integration tests for resource forking functionality using testcontainers PostgreSQL.

Tests the actual database operations for forking workflows and databases
against a real PostgreSQL instance with migrations applied.
"""

import pytest
import pytest_asyncio
import uuid
import json
from typing import AsyncGenerator

# Import fixtures - need explicit import to ensure they're available


# Test user IDs - using fixed UUIDs for consistent testing
TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000002"
ORG_OWNER_ID = "00000000-0000-0000-0000-000000000003"


@pytest_asyncio.fixture
async def setup_test_users(postgres_db):
    """Create test users in auth.users table."""
    # Insert test users
    await postgres_db.execute("""
        INSERT INTO auth.users (id, email) VALUES
            ($1, 'testuser@example.com'),
            ($2, 'otheruser@example.com'),
            ($3, 'orgowner@example.com')
        ON CONFLICT (id) DO NOTHING
    """, TEST_USER_ID, OTHER_USER_ID, ORG_OWNER_ID)

    yield
    # Cleanup is handled by transaction rollback in postgres_db fixture


@pytest_asyncio.fixture
async def setup_test_org(postgres_db, setup_test_users):
    """Create a test organization with members."""
    org_id = str(uuid.uuid4())

    # Create organization (no owner_id column - owner is tracked via organization_members)
    await postgres_db.execute("""
        INSERT INTO organizations (id, name, slug)
        VALUES ($1, 'Test Org', 'test-org')
    """, org_id)

    # Add members (owner role determines who owns the org)
    await postgres_db.execute("""
        INSERT INTO organization_members (organization_id, user_id, role)
        VALUES
            ($1, $2, 'owner'),
            ($1, $3, 'member')
    """, org_id, ORG_OWNER_ID, TEST_USER_ID)

    yield org_id


class TestForkWorkflowIntegration:
    """Integration tests for workflow forking."""

    @pytest.mark.asyncio
    async def test_fork_workflow_to_personal(self, postgres_db, setup_test_users):
        """Test forking a workflow to personal space."""
        # Create source workflow owned by another user
        source_id = str(uuid.uuid4())
        workflow_data = {"nodes": [], "edges": []}

        await postgres_db.execute("""
            INSERT INTO workflows (id, owner_id, name, description, workflow)
            VALUES ($1, $2, 'Source Workflow', 'Test workflow', $3)
        """, source_id, OTHER_USER_ID, json.dumps(workflow_data))

        # Share with test user (so they can fork it)
        await postgres_db.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ('workflow', $1, 'user', $2, 'view', $3)
        """, source_id, TEST_USER_ID, OTHER_USER_ID)

        # Fork the workflow
        forked_id = str(uuid.uuid4())
        await postgres_db.execute("""
            INSERT INTO workflows (id, owner_id, organization_id, name, description, workflow)
            SELECT $1, $2, NULL, 'Copy of ' || name, description, workflow
            FROM workflows WHERE id = $3
        """, forked_id, TEST_USER_ID, source_id)

        # Record the fork
        await postgres_db.execute("""
            INSERT INTO resource_forks (resource_type, source_id, forked_id, forked_by)
            VALUES ('workflow', $1, $2, $3)
        """, source_id, forked_id, TEST_USER_ID)

        # Verify the forked workflow
        forked = await postgres_db.fetchrow("""
            SELECT * FROM workflows WHERE id = $1
        """, forked_id)

        assert forked is not None
        assert forked['owner_id'] == uuid.UUID(TEST_USER_ID)
        assert forked['organization_id'] is None
        assert forked['name'] == 'Copy of Source Workflow'
        assert json.loads(forked['workflow']) == workflow_data

        # Verify fork record exists
        fork_record = await postgres_db.fetchrow("""
            SELECT * FROM resource_forks
            WHERE resource_type = 'workflow' AND source_id = $1 AND forked_id = $2
        """, source_id, forked_id)

        assert fork_record is not None
        assert fork_record['forked_by'] == uuid.UUID(TEST_USER_ID)

    @pytest.mark.asyncio
    async def test_fork_workflow_to_organization(self, postgres_db, setup_test_org):
        """Test forking a workflow to an organization."""
        org_id = setup_test_org

        # Create source workflow
        source_id = str(uuid.uuid4())
        workflow_data = {"nodes": [{"id": "1"}], "edges": []}

        await postgres_db.execute("""
            INSERT INTO workflows (id, owner_id, name, description, workflow)
            VALUES ($1, $2, 'Org Fork Source', 'Test workflow', $3)
        """, source_id, OTHER_USER_ID, json.dumps(workflow_data))

        # Share with test user
        await postgres_db.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ('workflow', $1, 'user', $2, 'view', $3)
        """, source_id, TEST_USER_ID, OTHER_USER_ID)

        # Fork to organization (owner_id is still the forker, but org_id is set)
        forked_id = str(uuid.uuid4())
        await postgres_db.execute("""
            INSERT INTO workflows (id, owner_id, organization_id, name, description, workflow)
            SELECT $1, $2, $3, 'Copy of ' || name, description, workflow
            FROM workflows WHERE id = $4
        """, forked_id, TEST_USER_ID, org_id, source_id)

        # Record the fork
        await postgres_db.execute("""
            INSERT INTO resource_forks (resource_type, source_id, forked_id, forked_by)
            VALUES ('workflow', $1, $2, $3)
        """, source_id, forked_id, TEST_USER_ID)

        # Verify the forked workflow
        forked = await postgres_db.fetchrow("""
            SELECT * FROM workflows WHERE id = $1
        """, forked_id)

        assert forked is not None
        assert forked['owner_id'] == uuid.UUID(TEST_USER_ID)  # Forker is owner
        assert forked['organization_id'] == uuid.UUID(org_id)  # In org
        assert forked['name'] == 'Copy of Org Fork Source'


class TestForkDatabaseIntegration:
    """Integration tests for database forking."""

    @pytest.mark.asyncio
    async def test_fork_database_schema_only(self, postgres_db, setup_test_users):
        """Test forking a database (schema only, no data)."""
        # Create source database
        source_id = str(uuid.uuid4())
        schema_def = {
            "name": {"type": "TEXT", "nullable": True},
            "age": {"type": "INTEGER", "nullable": True}
        }

        await postgres_db.execute("""
            INSERT INTO user_tables_metadata
                (id, owner_id, title, description, virtual_table_name, source, schema_definition)
            VALUES ($1, $2, 'Source DB', 'Test database', 'source_table', 'managed', $3)
        """, source_id, OTHER_USER_ID, json.dumps(schema_def))

        # Create actual table in user_tables schema
        await postgres_db.execute(f"""
            CREATE TABLE IF NOT EXISTS user_tables."{source_id}" (
                id SERIAL PRIMARY KEY,
                name TEXT,
                age INTEGER
            )
        """)

        # Insert some data
        await postgres_db.execute(f"""
            INSERT INTO user_tables."{source_id}" (name, age) VALUES
                ('Alice', 30),
                ('Bob', 25)
        """)

        # Share with test user
        await postgres_db.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ('database', $1, 'user', $2, 'view', $3)
        """, source_id, TEST_USER_ID, OTHER_USER_ID)

        # Fork the database (schema only)
        forked_id = str(uuid.uuid4())
        await postgres_db.execute("""
            INSERT INTO user_tables_metadata
                (id, owner_id, title, description, virtual_table_name, source, schema_definition)
            SELECT $1, $2, 'Copy of ' || title, description,
                   virtual_table_name || '_copy', 'managed', schema_definition
            FROM user_tables_metadata WHERE id = $3
        """, forked_id, TEST_USER_ID, source_id)

        # Create forked table (empty, schema only)
        await postgres_db.execute(f"""
            CREATE TABLE user_tables."{forked_id}" (
                id SERIAL PRIMARY KEY,
                name TEXT,
                age INTEGER
            )
        """)

        # Record the fork
        await postgres_db.execute("""
            INSERT INTO resource_forks (resource_type, source_id, forked_id, forked_by)
            VALUES ('database', $1, $2, $3)
        """, source_id, forked_id, TEST_USER_ID)

        # Verify forked metadata
        forked = await postgres_db.fetchrow("""
            SELECT * FROM user_tables_metadata WHERE id = $1
        """, forked_id)

        assert forked is not None
        assert forked['owner_id'] == uuid.UUID(TEST_USER_ID)
        assert forked['title'] == 'Copy of Source DB'

        # Verify forked table is EMPTY (schema only, no data copied)
        forked_count = await postgres_db.fetchval(f"""
            SELECT COUNT(*) FROM user_tables."{forked_id}"
        """)
        assert forked_count == 0

        # Verify source still has data
        source_count = await postgres_db.fetchval(f"""
            SELECT COUNT(*) FROM user_tables."{source_id}"
        """)
        assert source_count == 2

    @pytest.mark.asyncio
    async def test_fork_database_with_data(self, postgres_db, setup_test_users):
        """Test forking a database including data."""
        # Create source database
        source_id = str(uuid.uuid4())
        schema_def = {"product": {"type": "TEXT"}, "price": {"type": "NUMERIC"}}

        await postgres_db.execute("""
            INSERT INTO user_tables_metadata
                (id, owner_id, title, description, virtual_table_name, source, schema_definition)
            VALUES ($1, $2, 'Products DB', 'Product catalog', 'products', 'managed', $3)
        """, source_id, OTHER_USER_ID, json.dumps(schema_def))

        # Create actual table
        await postgres_db.execute(f"""
            CREATE TABLE user_tables."{source_id}" (
                id SERIAL PRIMARY KEY,
                product TEXT,
                price NUMERIC(10,2)
            )
        """)

        # Insert data
        await postgres_db.execute(f"""
            INSERT INTO user_tables."{source_id}" (product, price) VALUES
                ('Widget', 9.99),
                ('Gadget', 19.99),
                ('Thingamajig', 29.99)
        """)

        # Share with test user
        await postgres_db.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ('database', $1, 'user', $2, 'view', $3)
        """, source_id, TEST_USER_ID, OTHER_USER_ID)

        # Fork with data
        forked_id = str(uuid.uuid4())
        await postgres_db.execute("""
            INSERT INTO user_tables_metadata
                (id, owner_id, title, description, virtual_table_name, source, schema_definition)
            SELECT $1, $2, 'Copy of ' || title, description,
                   virtual_table_name || '_fork', 'managed', schema_definition
            FROM user_tables_metadata WHERE id = $3
        """, forked_id, TEST_USER_ID, source_id)

        # Create forked table WITH data
        await postgres_db.execute(f"""
            CREATE TABLE user_tables."{forked_id}" AS
            SELECT * FROM user_tables."{source_id}"
        """)

        # Record the fork
        await postgres_db.execute("""
            INSERT INTO resource_forks (resource_type, source_id, forked_id, forked_by)
            VALUES ('database', $1, $2, $3)
        """, source_id, forked_id, TEST_USER_ID)

        # Verify forked table has data
        forked_count = await postgres_db.fetchval(f"""
            SELECT COUNT(*) FROM user_tables."{forked_id}"
        """)
        assert forked_count == 3

        # Verify data matches
        forked_products = await postgres_db.fetch(f"""
            SELECT product, price FROM user_tables."{forked_id}" ORDER BY product
        """)
        assert len(forked_products) == 3
        assert forked_products[0]['product'] == 'Gadget'
        assert float(forked_products[0]['price']) == 19.99

    @pytest.mark.asyncio
    async def test_fork_database_to_organization(self, postgres_db, setup_test_org):
        """Test forking a database to an organization."""
        org_id = setup_test_org

        # Create source database
        source_id = str(uuid.uuid4())

        await postgres_db.execute("""
            INSERT INTO user_tables_metadata
                (id, owner_id, title, description, virtual_table_name, source, schema_definition)
            VALUES ($1, $2, 'Org Fork Source', 'Test', 'org_source', 'managed', '{}')
        """, source_id, OTHER_USER_ID)

        # Share with test user
        await postgres_db.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ('database', $1, 'user', $2, 'view', $3)
        """, source_id, TEST_USER_ID, OTHER_USER_ID)

        # Fork to organization
        forked_id = str(uuid.uuid4())
        await postgres_db.execute("""
            INSERT INTO user_tables_metadata
                (id, owner_id, organization_id, title, description, virtual_table_name, source, schema_definition)
            SELECT $1, $2, $3, 'Copy of ' || title, description,
                   virtual_table_name || '_orgfork', 'managed', schema_definition
            FROM user_tables_metadata WHERE id = $4
        """, forked_id, TEST_USER_ID, org_id, source_id)

        # Verify
        forked = await postgres_db.fetchrow("""
            SELECT * FROM user_tables_metadata WHERE id = $1
        """, forked_id)

        assert forked is not None
        assert forked['owner_id'] == uuid.UUID(TEST_USER_ID)  # Forker is owner
        assert forked['organization_id'] == uuid.UUID(org_id)  # In org


class TestForkPermissions:
    """Test fork permission checks."""

    @pytest.mark.asyncio
    async def test_cannot_fork_without_access(self, postgres_db, setup_test_users):
        """Test that forking fails without view access."""
        # Create private workflow (not shared with test user)
        source_id = str(uuid.uuid4())

        await postgres_db.execute("""
            INSERT INTO workflows (id, owner_id, name, description, workflow)
            VALUES ($1, $2, 'Private Workflow', 'Not shared', '{}')
        """, source_id, OTHER_USER_ID)

        # No share record for TEST_USER_ID

        # Check access - should return false/null
        has_access = await postgres_db.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM workflows w
                LEFT JOIN resource_shares rs ON rs.resource_id::text = w.id::text AND rs.resource_type = 'workflow'
                WHERE w.id = $1 AND (
                    w.owner_id = $2 OR
                    (rs.target_type = 'user' AND rs.target_user_id = $2)
                )
            )
        """, source_id, TEST_USER_ID)

        assert has_access is False

    @pytest.mark.asyncio
    async def test_can_fork_shared_resource(self, postgres_db, setup_test_users):
        """Test that forking works with view access."""
        # Create workflow shared with test user
        source_id = str(uuid.uuid4())

        await postgres_db.execute("""
            INSERT INTO workflows (id, owner_id, name, description, workflow)
            VALUES ($1, $2, 'Shared Workflow', 'Shared with test user', '{}')
        """, source_id, OTHER_USER_ID)

        # Share with test user
        await postgres_db.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ('workflow', $1, 'user', $2, 'view', $3)
        """, source_id, TEST_USER_ID, OTHER_USER_ID)

        # Check access - should return true
        has_access = await postgres_db.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM workflows w
                LEFT JOIN resource_shares rs ON rs.resource_id::text = w.id::text AND rs.resource_type = 'workflow'
                WHERE w.id = $1 AND (
                    w.owner_id = $2 OR
                    (rs.target_type = 'user' AND rs.target_user_id = $2)
                )
            )
        """, source_id, TEST_USER_ID)

        assert has_access is True


class TestForkAttribution:
    """Test fork attribution tracking."""

    @pytest.mark.asyncio
    async def test_fork_records_attribution(self, postgres_db, setup_test_users):
        """Test that fork records are created correctly."""
        source_id = str(uuid.uuid4())
        forked_id = str(uuid.uuid4())

        # Create source
        await postgres_db.execute("""
            INSERT INTO workflows (id, owner_id, name, description, workflow)
            VALUES ($1, $2, 'Source', 'Original', '{}')
        """, source_id, OTHER_USER_ID)

        # Record fork
        await postgres_db.execute("""
            INSERT INTO resource_forks (resource_type, source_id, forked_id, forked_by)
            VALUES ('workflow', $1, $2, $3)
        """, source_id, forked_id, TEST_USER_ID)

        # Query by source
        forks_from_source = await postgres_db.fetch("""
            SELECT * FROM resource_forks
            WHERE resource_type = 'workflow' AND source_id = $1
        """, source_id)
        assert len(forks_from_source) == 1
        assert forks_from_source[0]['forked_id'] == uuid.UUID(forked_id)

        # Query by forked resource
        fork_origin = await postgres_db.fetchrow("""
            SELECT * FROM resource_forks
            WHERE resource_type = 'workflow' AND forked_id = $1
        """, forked_id)
        assert fork_origin is not None
        assert fork_origin['source_id'] == uuid.UUID(source_id)
        assert fork_origin['forked_by'] == uuid.UUID(TEST_USER_ID)

    @pytest.mark.asyncio
    async def test_multiple_forks_from_same_source(self, postgres_db, setup_test_users):
        """Test that multiple users can fork the same source."""
        source_id = str(uuid.uuid4())
        forked_id_1 = str(uuid.uuid4())
        forked_id_2 = str(uuid.uuid4())

        # Create source
        await postgres_db.execute("""
            INSERT INTO workflows (id, owner_id, name, description, workflow)
            VALUES ($1, $2, 'Popular Workflow', 'Many forks', '{}')
        """, source_id, ORG_OWNER_ID)

        # Two different users fork it
        await postgres_db.execute("""
            INSERT INTO resource_forks (resource_type, source_id, forked_id, forked_by)
            VALUES
                ('workflow', $1, $2, $3),
                ('workflow', $1, $4, $5)
        """, source_id, forked_id_1, TEST_USER_ID, forked_id_2, OTHER_USER_ID)

        # Count forks
        fork_count = await postgres_db.fetchval("""
            SELECT COUNT(*) FROM resource_forks
            WHERE resource_type = 'workflow' AND source_id = $1
        """, source_id)
        assert fork_count == 2


class TestForkListingBehavior:
    """Tests that verify forked resources appear in the correct context."""

    @pytest.mark.asyncio
    async def test_org_forked_workflow_appears_in_org_context_only(self, postgres_db, setup_test_org):
        """
        When a workflow is forked to an organization:
        - It should appear in org context listing
        - It should NOT appear in personal context listing
        """
        org_id = setup_test_org

        # Create source workflow (personal, owned by other user)
        source_id = str(uuid.uuid4())
        await postgres_db.execute("""
            INSERT INTO workflows (id, owner_id, name, description, workflow)
            VALUES ($1, $2, 'Source Workflow', 'Test', '{}')
        """, source_id, OTHER_USER_ID)

        # Share with test user so they can fork it
        await postgres_db.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ('workflow', $1, 'user', $2, 'view', $3)
        """, source_id, TEST_USER_ID, OTHER_USER_ID)

        # Fork to organization - this sets organization_id
        forked_id = str(uuid.uuid4())
        await postgres_db.execute("""
            INSERT INTO workflows (id, owner_id, organization_id, name, description, workflow)
            VALUES ($1, $2, $3, 'Forked to Org', 'Forked', '{}')
        """, forked_id, TEST_USER_ID, org_id)

        # Record fork
        await postgres_db.execute("""
            INSERT INTO resource_forks (resource_type, source_id, forked_id, forked_by)
            VALUES ('workflow', $1, $2, $3)
        """, source_id, forked_id, TEST_USER_ID)

        # Query: ORG CONTEXT - should find the forked workflow
        org_workflows = await postgres_db.fetch("""
            SELECT DISTINCT w.id, w.name, w.organization_id
            FROM workflows w
            LEFT JOIN resource_shares rs ON rs.resource_id = w.id
                AND rs.resource_type = 'workflow'
                AND rs.target_type = 'organization'
                AND rs.target_org_id = $1
            WHERE w.organization_id = $1
               OR rs.id IS NOT NULL
        """, org_id)

        org_workflow_ids = [str(w['id']) for w in org_workflows]
        assert forked_id in org_workflow_ids, "Forked workflow should appear in org context"

        # Query: PERSONAL CONTEXT - should NOT find the forked workflow
        personal_workflows = await postgres_db.fetch("""
            SELECT w.id, w.name, w.organization_id
            FROM workflows w
            LEFT JOIN resource_shares rs ON rs.resource_id = w.id
                AND rs.resource_type = 'workflow'
                AND rs.target_type = 'organization'
            WHERE w.owner_id = $1
              AND w.organization_id IS NULL
              AND rs.id IS NULL
        """, TEST_USER_ID)

        personal_workflow_ids = [str(w['id']) for w in personal_workflows]
        assert forked_id not in personal_workflow_ids, "Forked org workflow should NOT appear in personal context"

    @pytest.mark.asyncio
    async def test_org_forked_database_appears_in_org_context_only(self, postgres_db, setup_test_org):
        """
        When a database is forked to an organization:
        - It should appear in org context listing
        - It should NOT appear in personal context listing
        """
        org_id = setup_test_org

        # Create source database (personal, owned by other user)
        source_id = str(uuid.uuid4())
        await postgres_db.execute("""
            INSERT INTO user_tables_metadata (id, owner_id, title, virtual_table_name, schema_definition)
            VALUES ($1, $2, 'Source DB', 'source_db', '{}')
        """, source_id, OTHER_USER_ID)

        # Share with test user
        await postgres_db.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ('database', $1, 'user', $2, 'view', $3)
        """, source_id, TEST_USER_ID, OTHER_USER_ID)

        # Fork to organization - this sets organization_id
        forked_id = str(uuid.uuid4())
        await postgres_db.execute("""
            INSERT INTO user_tables_metadata (id, owner_id, organization_id, title, virtual_table_name, schema_definition)
            VALUES ($1, $2, $3, 'Forked to Org', 'forked_db', '{}')
        """, forked_id, TEST_USER_ID, org_id)

        # Record fork
        await postgres_db.execute("""
            INSERT INTO resource_forks (resource_type, source_id, forked_id, forked_by)
            VALUES ('database', $1, $2, $3)
        """, source_id, forked_id, TEST_USER_ID)

        # Query: ORG CONTEXT - should find the forked database
        org_tables = await postgres_db.fetch("""
            SELECT DISTINCT t.id, t.title, t.organization_id
            FROM user_tables_metadata t
            LEFT JOIN resource_shares rs ON rs.resource_id = t.id
                AND rs.resource_type = 'database'
                AND rs.target_type = 'organization'
                AND rs.target_org_id = $1
            WHERE t.organization_id = $1
               OR rs.id IS NOT NULL
        """, org_id)

        org_table_ids = [str(t['id']) for t in org_tables]
        assert forked_id in org_table_ids, "Forked database should appear in org context"

        # Query: PERSONAL CONTEXT - should NOT find the forked database
        personal_tables = await postgres_db.fetch("""
            SELECT t.id, t.title, t.organization_id
            FROM user_tables_metadata t
            LEFT JOIN resource_shares rs ON rs.resource_id = t.id
                AND rs.resource_type = 'database'
                AND rs.target_type = 'organization'
            WHERE t.owner_id = $1
              AND t.organization_id IS NULL
              AND rs.id IS NULL
        """, TEST_USER_ID)

        personal_table_ids = [str(t['id']) for t in personal_tables]
        assert forked_id not in personal_table_ids, "Forked org database should NOT appear in personal context"

    @pytest.mark.asyncio
    async def test_personal_forked_workflow_appears_in_personal_context_only(self, postgres_db, setup_test_users):
        """
        When a workflow is forked to personal:
        - It should appear in personal context listing
        - It should NOT appear in any org context listing
        """
        # Create source workflow
        source_id = str(uuid.uuid4())
        await postgres_db.execute("""
            INSERT INTO workflows (id, owner_id, name, description, workflow)
            VALUES ($1, $2, 'Source Workflow', 'Test', '{}')
        """, source_id, OTHER_USER_ID)

        # Share with test user
        await postgres_db.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ('workflow', $1, 'user', $2, 'view', $3)
        """, source_id, TEST_USER_ID, OTHER_USER_ID)

        # Fork to personal - organization_id is NULL
        forked_id = str(uuid.uuid4())
        await postgres_db.execute("""
            INSERT INTO workflows (id, owner_id, organization_id, name, description, workflow)
            VALUES ($1, $2, NULL, 'Forked to Personal', 'Forked', '{}')
        """, forked_id, TEST_USER_ID)

        # Record fork
        await postgres_db.execute("""
            INSERT INTO resource_forks (resource_type, source_id, forked_id, forked_by)
            VALUES ('workflow', $1, $2, $3)
        """, source_id, forked_id, TEST_USER_ID)

        # Query: PERSONAL CONTEXT - should find the forked workflow
        personal_workflows = await postgres_db.fetch("""
            SELECT w.id, w.name, w.organization_id
            FROM workflows w
            LEFT JOIN resource_shares rs ON rs.resource_id = w.id
                AND rs.resource_type = 'workflow'
                AND rs.target_type = 'organization'
            WHERE w.owner_id = $1
              AND w.organization_id IS NULL
              AND rs.id IS NULL
        """, TEST_USER_ID)

        personal_workflow_ids = [str(w['id']) for w in personal_workflows]
        assert forked_id in personal_workflow_ids, "Forked personal workflow should appear in personal context"

        # Verify it has no organization_id
        forked = await postgres_db.fetchrow("SELECT organization_id FROM workflows WHERE id = $1", forked_id)
        assert forked['organization_id'] is None, "Personal fork should have NULL organization_id"
