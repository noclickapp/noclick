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

    # Workflow MCP Tools
    "workflow:mcp:search_nodes": {
        "name": "search_workflow_nodes",
        "description": "Search available workflow node types. Returns type, label, description, config_types (with required_fields), and credentials. Use get_node_config_schema for full JSON schema.",
        "tags": {"workflow", "search", "nodes"},
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    },
    "workflow:mcp:get_node_config_schema": {
        "name": "get_workflow_node_config_schema",
        "description": "Get the full JSON schema for a specific node config type. Call search_workflow_nodes first to see available config_types for each node.",
        "tags": {"workflow", "schema", "nodes"},
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    },
    "workflow:mcp:add_node": {
        "name": "add_workflow_node",
        "description": "Add a new node to the currently open workflow. If prev_node_id is provided, auto-connects the new node to that node. Returns the new node_id.",
        "tags": {"workflow", "create", "nodes"},
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
        },
    },
    "workflow:mcp:remove_node": {
        "name": "remove_workflow_node",
        "description": "Remove a node and its connections from the currently open workflow.",
        "tags": {"workflow", "delete", "nodes"},
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
        },
    },
    "workflow:mcp:get_selected_node": {
        "name": "get_selected_workflow_node",
        "description": "Get the currently selected node in the workflow canvas. Returns null if no node is selected.",
        "tags": {"workflow", "read", "selection"},
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    },
    "workflow:mcp:get_open_workflow": {
        "name": "get_open_workflow",
        "description": "Get the currently open workflow in the editor. Returns workflow_id, node list (id and type), and running state. Use this first when user gives vague requests like 'delete all X nodes' to identify which workflow they're referring to. Returns null if no workflow is open.",
        "tags": {"workflow", "read", "context"},
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    },
    "workflow:mcp:get_node_output": {
        "name": "get_workflow_node_output",
        "description": "Get the execution output of workflow nodes. If a node is still running, waits until completion (with timeout). Call this after run_workflow to get results from specific nodes.",
        "tags": {"workflow", "read", "output", "async"},
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    },
    "workflow:mcp:get_node_input": {
        "name": "get_workflow_node_input",
        "description": "Get the input data flowing into a node from connected upstream nodes.",
        "tags": {"workflow", "read", "input"},
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    },
    "workflow:mcp:run_workflow": {
        "name": "run_workflow",
        "description": "Start executing the currently open workflow. Returns immediately - use get_workflow_node_output() to wait for specific node results.",
        "tags": {"workflow", "execute", "run"},
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
        },
    },
    "workflow:mcp:create_workflow": {
        "name": "create_workflow",
        "description": "Create a new workflow and open it in the editor. Returns the new workflow_id.",
        "tags": {"workflow", "create"},
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
        },
    },
    "workflow:mcp:open_workflow": {
        "name": "open_workflow",
        "description": "Open an existing workflow in the editor by its ID. Use list_workflows to find workflow IDs.",
        "tags": {"workflow", "open", "navigation"},
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    },
    "workflow:mcp:list_workflows": {
        "name": "list_workflows",
        "description": "List available workflows, optionally filtering by search query. Returns workflow IDs, names, and descriptions.",
        "tags": {"workflow", "list", "search"},
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    },
    "workflow:mcp:delete_workflow": {
        "name": "delete_workflow",
        "description": "Permanently delete a workflow and all its nodes/edges. This action cannot be undone.",
        "tags": {"workflow", "delete", "destructive"},
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
        },
    },
    "workflow:mcp:update_workflow_metadata": {
        "name": "update_workflow_metadata",
        "description": "Update a workflow's name and/or description. Only provided fields are updated.",
        "tags": {"workflow", "update", "metadata"},
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    },
    "workflow:mcp:list_saved_outputs": {
        "name": "list_saved_outputs",
        "description": "List saved outputs (mock data) available for a specific node type. Use the saved_output_id to set mock data on a node.",
        "tags": {"workflow", "mock", "list"},
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    },
    "workflow:mcp:set_node_mock": {
        "name": "set_node_mock_output",
        "description": "Set mock output data for a node. Provide either saved_output_id to use saved data, or output to set raw data directly. Use clear=true to remove mock data.",
        "tags": {"workflow", "mock", "modify"},
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    },
    "workflow:mcp:set_node_disabled": {
        "name": "set_node_disabled",
        "description": "Enable or disable a workflow node. Disabled nodes are skipped during execution.",
        "tags": {"workflow", "modify", "nodes"},
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    },
    "workflow:mcp:run_node": {
        "name": "run_single_node",
        "description": "Execute a single node in the workflow. Previous nodes must have output data (either from prior execution or mock data). Use get_node_output to retrieve results.",
        "tags": {"workflow", "execute", "nodes"},
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
        },
    },
    "workflow:mcp:update_node_config": {
        "name": "update_workflow_node_config",
        "description": "Update a workflow node's configuration. Use get_node_config_schema first to see the expected config structure for the node type.",
        "tags": {"workflow", "modify", "nodes", "config"},
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    },
    "workflow:mcp:batch_update_node_config": {
        "name": "batch_update_workflow_node_config",
        "description": "Update multiple workflow nodes' configurations in a single operation. More efficient than calling update_workflow_node_config multiple times. Pass a list of {node_id, config} updates.",
        "tags": {"workflow", "modify", "nodes", "config", "batch"},
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    },
    "workflow:mcp:batch_add_node": {
        "name": "batch_add_workflow_nodes",
        "description": "Add multiple nodes and edges to a workflow in a single operation. More efficient than calling add_workflow_node multiple times. Use temp_id in nodes to reference them in edges before real IDs are assigned.",
        "tags": {"workflow", "create", "nodes", "batch"},
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
        },
    },
    "workflow:mcp:get_execution_status": {
        "name": "get_workflow_execution_status",
        "description": "Get the status of a workflow execution. Returns execution_id, status (running/completed/failed), timestamps, nodes_executed count, and error message if failed. Use after run_workflow to check completion.",
        "tags": {"workflow", "status", "execution"},
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    },
    "workflow:mcp:list_credentials": {
        "name": "list_credentials",
        "description": "List available OAuth credentials/connections. Use to check if required credentials exist before configuring nodes. Filter by credential_type (e.g., 'google_sheets_oauth') to find specific connections.",
        "tags": {"workflow", "credentials", "list"},
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    },
    "workflow:mcp:load_field_options": {
        "name": "load_node_field_options",
        "description": "Load dynamic options for a node field (e.g., list of spreadsheets for spreadsheet_id field). Supports search_query for filtering, depends_on for cascading fields (e.g., sheet names depend on spreadsheet_id), and pagination.",
        "tags": {"workflow", "options", "dynamic"},
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    },
    "workflow:mcp:get_node_config": {
        "name": "get_workflow_node_config",
        "description": "Get a specific node's full configuration by ID. Returns node type, position, and all config fields. Use this to inspect any node without requiring it to be selected in the UI.",
        "tags": {"workflow", "read", "nodes", "config"},
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    },
    "workflow:mcp:add_edge": {
        "name": "add_workflow_edge",
        "description": "Add an edge (connection) between two nodes in the workflow. Specify source_id and target_id to create a directional connection.",
        "tags": {"workflow", "create", "edges"},
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
        },
    },
    "workflow:mcp:remove_edge": {
        "name": "remove_workflow_edge",
        "description": "Remove an edge from the workflow. Specify either edge_id directly, or source_id + target_id to find and remove the edge.",
        "tags": {"workflow", "delete", "edges"},
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
        },
    },
    "workflow:mcp:update_node_position": {
        "name": "update_workflow_node_position",
        "description": "Update a node's position in the workflow canvas. Provide x and y coordinates.",
        "tags": {"workflow", "modify", "nodes", "position"},
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    },
    "workflow:mcp:update_interface": {
        "name": "update_interface",
        "description": (
            "Update the interface layout for a workflow. Uses XML commands to position and resize "
            "interface blocks on a 12-column grid (row height 40px).\n\n"
            "XML commands:\n"
            '  <set_block_layout id="node-id" x="0" y="0" w="6" h="5" /> - Position/resize a block\n'
            '  <remove_block id="node-id" /> - Remove a block from the grid (keeps the workflow node)\n'
            '  <auto_layout /> - Auto-arrange all blocks in a 2-column grid\n'
            '  <auto_layout strategy="stack" /> - Auto-arrange in a single column\n\n'
            "Block id must be an existing interface-* workflow node ID. "
            "Any interface nodes not yet on the grid are auto-created with defaults.\n"
            "Each block in the response includes minW/minH constraints."
        ),
        "tags": {"workflow", "modify", "interface", "layout"},
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    },
}
