"""
NoClick MCP node for workflow automation.

Provides NoClick's own MCP tools (workflow CRUD, node management, execution, etc.)
to AI Agent nodes without requiring authentication — the user is already logged in.
Issues a short-lived MCP JWT so all agent types (the in-process LLM agent in
agent_node, Codex, Claude Code, OpenCode) can connect to the NoClick MCP server
as a standard MCP endpoint.
"""

import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)

# Tools excluded entirely (require browser session or are meta tools)
_EXCLUDED_TOOLS = frozenset(
    {
        "get_selected_node",
        "open_workflow",
        "get_current_workflow",
        "report_bug",
        "request_feature",
    }
)

# Tools that only make sense with unrestricted scope — hidden when scoped to specific workflows
_GLOBAL_ONLY_TOOLS = frozenset(
    {
        "list_workflows",
        "create_workflow",
        "delete_workflow",
        "get_workflow_folders",
        "update_folders",
        "list_workspaces",
        "switch_workspace",
    }
)


class NoClickConfig(BaseModel):
    """Configuration for the NoClick MCP tool provider node."""

    scope: str = Field(
        "all_workflows",
        title="Scope",
        description="Which workflows the agent can access",
        json_schema_extra={
            "enum": ["all_workflows", "this_workflow", "specific_workflows"],
            "enumNames": ["All workflows", "This workflow only", "Specific workflows"],
            "x-enum-searchable": True,
        },
    )
    allowed_workflow_ids: str = Field(
        "",
        title="Allowed Workflows",
        description="Select workflows the agent can access",
        json_schema_extra={
            "ui:show-if": {"field": "scope", "contains": "specific_workflows"},
            "ui:widget": "workflow_picker",
        },
    )


class NoClickNodeConfig(NodeConfig[NoClickConfig, None]):
    """Full configuration for NoClick node (no credentials needed)."""

    pass


class NoClickNode(WorkflowNode):
    """
    NoClick MCP tool provider node.

    Discovers tools from the in-process NoClickMCPServer singleton and outputs
    standard MCP tool definitions with a JWT bearer token. All agent types
    (the in-process LLM agent, Codex, Claude Code, OpenCode) can connect to the
    NoClick MCP server using these credentials.

    Supports three scopes:
    - all_workflows: Full access to all NoClick MCP tools
    - this_workflow: Tools scoped to the current workflow only
    - specific_workflows: Tools scoped to a specific set of workflow IDs
    """

    edit_examples = [
        "Restrict agent to this workflow only",
        "Grant access to specific workflows",
        "Allow agent to access all workflows",
        "Limit tools to this workflow scope",
        "Switch to global scope with all tools",
        "Configure multi-workflow access",
        "Change from specific to all workflows",
    ]

    @classmethod
    def get_config_model(cls) -> type:
        return NoClickNodeConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Load dynamic options for the allowed_workflow_ids field."""
        if field_name != "allowed_workflow_ids":
            return []

        user_id = (context or {}).get("_user_id")
        if not user_id:
            return []

        try:
            from utils.database_pool import get_native_pool

            pool = get_native_pool()
            if search:
                rows = await pool.fetch(
                    "SELECT id, name FROM workflows WHERE owner_id = $1 AND deleted_at IS NULL AND name ILIKE $2 ORDER BY updated_at DESC LIMIT 50",
                    user_id,
                    f"%{search}%",
                )
            else:
                rows = await pool.fetch(
                    "SELECT id, name FROM workflows WHERE owner_id = $1 AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 50",
                    user_id,
                )
            return [
                {"value": str(row["id"]), "label": row["name"] or str(row["id"])}
                for row in rows
            ]
        except Exception as e:
            logger.error(f"[NoClickNode] Failed to load workflow options: {e}")
            return []

    def _get_mcp_server_url(self) -> str:
        """Get the NoClick MCP server URL for the current process."""
        import os

        # MCP_BASE_URL is authoritative (production). Otherwise derive from
        # the PORT env var that uvicorn sets for each backend process.
        base = os.getenv("MCP_BASE_URL")
        if not base:
            port = os.getenv("PORT", "8000")
            base = f"http://localhost:{port}"
        return f"{base}/mcp"

    def _issue_token(self) -> str:
        """Issue a short-lived MCP JWT for the current user."""
        from mcp_adapter.auth.tokens import issue_mcp_token

        return issue_mcp_token(
            user_id=self.user_id,
            client_id="noclick-workflow-node",
            scopes=["mcp:tools"],
            expiry_hours=1,
        )

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Discover NoClick MCP tools and return standard MCP tool definitions.

        Issues a JWT bearer token so all agent types can authenticate with
        the NoClick MCP server over HTTP.
        """
        from mcp_server import get_mcp_server

        logger.info(f"[NoClickNode] Executing node {self.node_id}")

        server = get_mcp_server()
        if not server:
            return {
                "type": "mcp_tool_definitions",
                "error": "NoClick MCP server not initialized",
                "tool_count": 0,
                "tools": [],
            }

        # Parse scope config
        scope = "all_workflows"
        allowed_ids: Optional[List[str]] = None

        if self.config and isinstance(self.config, NoClickNodeConfig):
            scope = self.config.config.scope
            if (
                scope == "specific_workflows"
                and self.config.config.allowed_workflow_ids
            ):
                allowed_ids = [
                    wid.strip()
                    for wid in self.config.config.allowed_workflow_ids.split(",")
                    if wid.strip()
                ]
        elif self.node_data:
            scope = self.node_data.get("scope", "all_workflows")
            raw_ids = self.node_data.get("allowed_workflow_ids", "")
            if scope == "specific_workflows" and raw_ids:
                allowed_ids = [wid.strip() for wid in raw_ids.split(",") if wid.strip()]

        is_scoped = scope in ("this_workflow", "specific_workflows")

        logger.info(f"[NoClickNode] Scope: {scope}, workflow_id: {self.workflow_id}")

        # Issue a short-lived JWT and build MCP server config
        server_url = self._get_mcp_server_url()
        access_token = self._issue_token()

        mcp_server_config = {
            "url": server_url,
            "transport_type": "shttp",
            "access_token": access_token,
            "auth_type": "oauth",
        }

        try:
            fastmcp_tools = await server.mcp.get_tools()
            tools: List[Dict[str, Any]] = []

            for tool_name, tool in fastmcp_tools.items():
                if tool_name in _EXCLUDED_TOOLS:
                    continue

                # When scoped, skip global-only tools
                if is_scoped and tool_name in _GLOBAL_ONLY_TOOLS:
                    continue

                # Convert inputSchema to our parameter list format
                mcp_tool = tool.to_mcp_tool()
                input_schema = mcp_tool.inputSchema or {}
                properties = input_schema.get("properties", {})
                required = input_schema.get("required", [])

                parameters = []
                for param_name, param_schema in properties.items():
                    # When scoped, hide workflow_id param (it will be auto-injected)
                    if is_scoped and param_name == "workflow_id":
                        continue

                    parameters.append(
                        {
                            "name": param_name,
                            "type": param_schema.get("type", "string"),
                            "description": param_schema.get(
                                "description", f"Parameter: {param_name}"
                            ),
                            "required": param_name in required,
                            "default": param_schema.get("default"),
                        }
                    )

                tools.append(
                    {
                        "type": "tool_definition",
                        "tool_type": "mcp",
                        "tool_name": f"noclick_{tool_name}",
                        "original_tool_name": tool_name,
                        "tool_description": tool.description
                        or f"NoClick tool: {tool_name}",
                        "parameters": parameters,
                        "mcp_server_config": mcp_server_config,
                    }
                )

                logger.debug(f"[NoClickNode] Discovered tool: noclick_{tool_name}")

            logger.info(f"[NoClickNode] Discovered {len(tools)} tools (scope={scope})")

            return {
                "type": "mcp_tool_definitions",
                "server_name": "noclick",
                "server_url": server_url,
                "tool_count": len(tools),
                "tools": tools,
            }

        except Exception as e:
            logger.error(f"[NoClickNode] Error discovering tools: {e}", exc_info=True)
            return {
                "type": "mcp_tool_definitions",
                "error": str(e),
                "tool_count": 0,
                "tools": [],
            }
