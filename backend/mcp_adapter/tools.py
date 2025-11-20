"""
MCP (Model Context Protocol) tool configurations.

Each event is automatically exposed as an MCP tool with the specified metadata.
Metadata helps LLMs understand and use tools more effectively.
"""

from typing import Dict

# MCP Events Configuration
# Maps socket event names to MCP tool metadata
MCP_EVENTS: Dict[str, Dict[str, any]] = {
    "user_database:create_table": {
        "name": "create_database_table",
        "description": "Create a new database table with specified columns and schema",
        "tags": {"database", "create", "schema"},
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
        },
    },
    "user_database:list_tables": {
        "name": "list_database_tables",
        "description": "List all database tables with their schemas and metadata",
        "tags": {"database", "read", "list"},
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    },
    "user_database:update_table": {
        "name": "update_database_table",
        "description": "Update an existing database table's metadata or schema",
        "tags": {"database", "update", "modify"},
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
        },
    },
    "user_database:delete_table": {
        "name": "delete_database_table",
        "description": "Permanently delete a database table and all its data",
        "tags": {"database", "delete", "destructive"},
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
        },
    },
    "user_database:sql": {
        "name": "execute_sql_query",
        "description": "Execute a SQL query on the user's database (SELECT, INSERT, UPDATE, DELETE)",
        "tags": {"database", "sql", "query"},
        "annotations": {
            "readOnlyHint": False,  # Can be read or write depending on query
            "destructiveHint": False,  # Depends on the query
            "idempotentHint": False,
        },
    },
}
