"""Credential-level coordinator tools over the existing connection and node APIs.

Connections remain account resources. No throwaway workflow is created to
connect a provider, discover its operations, or perform an authorized action.
"""

from uuid import UUID

from repositories.credentials import CredentialsRepo
from utils.credential_operations import connection_catalog, operation_catalog, operation_tool, search_operations
from utils.credential_tool_registry import CredentialToolRegistry


def credential_summary(row):
    # Metadata is provider-defined and can contain tokens. Export only known
    # public identity fields, never the whole metadata or credential blob.
    identity = {key: value[:320] for key in (
        "email", "phone_number", "username", "account_name", "workspace_name", "team_name",
    ) if isinstance(value := (row.metadata or {}).get(key), str) and value.strip()}
    return {"id": row.id, "name": row.name, "credential_type": row.credential_type,
            "identity": identity, "revoked": bool(row.revoked_at), "access": row.my_permission}


def credential_tool_params(tool):
    identity = {"credential_id": {"type": "string"}}
    operation = {**identity, "node_type": {"type": "string"}, "operation": {"type": "string"}}
    return [
        tool("list_credentials", "List accessible connections without secrets. No workflow is required.",
             {"query": {"type": "string"}, "offset": {"type": "integer", "minimum": 0}}),
        tool("search_credential_tools", "Search operations across connected accounts and load the top matching tools "
             "for direct calls. Returns tool names and compatible credential IDs with account identities. "
             "Each loaded tool requires credential_id: select the requested account, never guess between ambiguous accounts. "
             "Use list_credentials for account identity (including email) without calling a provider. "
             "Optionally narrow to credential_id or use offset for more matches.",
             {"query": {"type": "string"}, **identity, "offset": {"type": "integer", "minimum": 0}}, ["query"]),
        tool("find_connections", "Find supported connection types before creating a connection link. Search by service name.",
             {"query": {"type": "string"}}, ["query"]),
        tool("connect_credential", "Create a secure NoClick link to connect an account without creating a workflow. "
             "Return the link to the user; never ask for tokens or verification codes in chat. "
             "Completion wakes you automatically; do not ask for a confirmation message in chat. "
             "Use find_connections for credential_type. Paid phone numbers use request_phone_number instead.",
             {"credential_type": {"type": "string"}, "message": {"type": "string", "maxLength": 1000}}, ["credential_type"]),
        tool("credential_connection_status", "Check whether a standalone connection was completed. Returns its credential ID when ready.",
             {"request_id": {"type": "string"}}, ["request_id"]),
        tool("credential_operation_status", "Inspect a long-running credential operation by operation_id. "
             "Pending or expired is not success and is not permission to repeat the action.",
             {"operation_id": {"type": "string"}}, ["operation_id"]),
        tool("request_credential_permissions", "Send the owner a link to review this connection's approval rules. "
             "Only the human can unlock tools. Saving the review wakes you automatically; inspect the result before continuing.",
             identity, ["credential_id"]),
        tool("credential_operations", "Discover this connection's available operations. Pass node_type and operation to get "
             "the complete argument schema and optional lookup schema before calling it. Provider OAuth scopes may require reconnection.",
             {**operation, "query": {"type": "string"}, "offset": {"type": "integer", "minimum": 0}}, ["credential_id"]),
        tool("call_credential_operation", "Perform one discovered operation using this credential directly. "
             "Only act within the user's authorization. Restrictions create a pending human approval; "
             "pending is NOT success. Do not evade restrictions with another operation, credential or agent.",
             {**operation, "arguments": {"type": "object"}}, [*operation, "arguments"]),
        tool("require_credential_approval", "Require human approval for operations on this specific credential. "
             "This only adds restrictions; you cannot remove them. Use operation keys from credential_operations "
             "or '*' for every operation. Changes apply to all callers including MCP and agents.",
             {**identity, "operations": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
             ["credential_id", "operations"]),
        tool("lookup_credential_options", "Resolve valid IDs for an operation's fields using the lookup schema returned "
             "by credential_operations. Restricted credentials also require approval for these reads.",
             {**operation, "field": {"type": "string"}, "context": {"type": "object"},
              "search": {"type": "string"}, "page_token": {"type": "string"}}, [*operation, "field"]),
    ]


class CredentialActions:
    def __init__(self, *, pool, user_id, organization_id=None, conversation_id=None, continuation=None, native_tools=False):
        self.pool = pool
        self.user_id = user_id
        self.organization_id = organization_id
        self.conversation_id = conversation_id
        self.continuation = continuation
        self.repo = CredentialsRepo(pool)
        self.registry = CredentialToolRegistry()
        self.native_tools = native_tools

    async def _credentials(self):
        return await self.repo.list_accessible(self.user_id, self.organization_id)

    async def _credential(self, credential_id):
        wanted = str(UUID(credential_id))
        row = next((row for row in await self._credentials() if row.id == wanted), None)
        if row is None:
            raise ValueError("Credential not found or not accessible.")
        if row.revoked_at:
            raise ValueError("This connection is revoked. Ask the user to reconnect it.")
        return row

    async def list_credentials(self, query="", offset=0):
        rows = [credential_summary(row) for row in await self._credentials()]
        rows = [row for row in rows if query.casefold() in
                f"{row['name']} {row['credential_type']} {' '.join(row['identity'].values())}".casefold()]
        offset = max(0, offset)
        return {"credentials": rows[offset:offset + 30], "total": len(rows),
                "next_offset": offset + 30 if len(rows) > offset + 30 else None}

    async def search_credential_tools(self, query, credential_id=None, offset=0):
        rows = [await self._credential(credential_id)] if credential_id else [
            row for row in await self._credentials() if not row.revoked_at]
        operations, candidates, catalogs = {}, {}, {}
        for row in rows:
            if row.credential_type not in catalogs:
                catalogs[row.credential_type] = operation_catalog(row.credential_type)
            for op in catalogs[row.credential_type]:
                operations.setdefault(op["key"], op)
                candidates.setdefault(op["key"], []).append(row)
        matches = search_operations(operations.values(), query)
        offset = max(0, offset)
        results = []
        for op in matches[offset:offset + 3]:
            compatible = candidates[op["key"]]
            definitions, configs = operation_tool(compatible[0].credential_type, op["node_type"], op["operation"])
            names = self.registry.load(op["node_type"], op["operation"], definitions, configs)
            results.append({**op, "tool_names": names,
                            "credentials": [credential_summary(row) for row in compatible[:30]],
                            "credential_count": len(compatible)})
        return {"operations": results, "total": len(matches),
                "next_offset": offset + 3 if len(matches) > offset + 3 else None,
                "instructions": "Call the loaded tool with the chosen credential_id and typed arguments. "
                "Search again to reload a tool no longer visible. Restrictions apply to the selected credential."}

    async def find_connections(self, query):
        methods, _ = connection_catalog()
        matches = [{"credential_type": value["credential_type"], "name": value["name"]}
                   for value in methods.values()
                   if query.casefold() in f"{value['name']} {value['credential_type']}".casefold()]
        return {"connections": matches[:30], "total": len(matches)}

    async def connect_credential(self, credential_type, message=None):
        from utils.email import credential_provide_url
        from mcp_adapter.auth.endpoints import get_frontend_url

        if credential_type == "phone_number":
            raise ValueError("Use request_phone_number for the owner-confirmed purchase flow.")
        if credential_type not in connection_catalog()[0]:
            raise ValueError("Unknown connection type. Use find_connections first.")
        row = await self.repo.upsert_credential_request(
            requester_id=self.user_id, target_email="", credential_type=credential_type,
            message=(message or "Connect this account for your coordinator.")[:1000], reuse_pending=True,
            continuation=self.continuation,
        )
        return {"status": row.status, "request_id": row.id,
                "url": credential_provide_url(row.token, get_frontend_url()),
                "auto_resume": self.continuation is not None}

    async def credential_connection_status(self, request_id):
        row = await self.repo.connection_request_status(str(UUID(request_id)), self.user_id)
        if row is None:
            raise ValueError("Connection request not found.")
        return row

    async def credential_operation_status(self, operation_id):
        from repositories.coordinator_operations import CoordinatorOperationRepo
        row = await CoordinatorOperationRepo(self.pool).get(str(UUID(operation_id)), self.user_id)
        if row is None:
            raise ValueError("Operation not found or not accessible.")
        return {"operation_id": str(row["id"]), "delivery_status": row["status"], "outcome": row["payload"]}

    async def load_approval_tools(self, payload):
        """Restore schemas on a cold approval wakeup; never consume the grant.

        Ordinary tools are turn-local. The durable approval already identifies
        the operation/account, so no separate persisted tool registry is needed.
        """
        if payload.get("status") != "approved":
            return
        row = await self._credential(payload["credential_id"])
        node_type, operation = payload["node_type"], payload["operation"]
        if operation != "__lookup__":
            tools, configs = operation_tool(row.credential_type, node_type, operation)
            self.registry.load(node_type, operation, tools, configs)
            return
        field = payload["arguments"]["field_name"]
        for op in operation_catalog(row.credential_type, node_type):
            tools, configs = operation_tool(row.credential_type, node_type, op["operation"])
            if any(field in c.get("fields", {}).values() for c in configs.values() if c["tool_type"] == "node_op_lookup"):
                self.registry.load(node_type, op["operation"], tools, configs)
                return

    async def credential_operations(self, credential_id, node_type=None, operation=None, query="", offset=0):
        from repositories.credential_approvals import CredentialApprovalRepo
        row = await self._credential(credential_id)
        policy = await CredentialApprovalRepo(self.pool).policy(row.id, self.user_id, self.organization_id)
        if operation:
            if not node_type:
                raise ValueError("node_type is required for an operation schema.")
            tools, configs = operation_tool(row.credential_type, node_type, operation)
            names = self.registry.load(node_type, operation, tools, configs) if self.native_tools else []
            return {"tools": tools, "call_tool": "call_credential_operation",
                    **({"loaded_tools": names} if names else {}),
                    "instructions": ("Call the loaded tool with credential_id and typed arguments." if names else
                        "Use the operation tool's parameters as arguments to call_credential_operation; use lookup_credential_options for the lookup descriptor."),
                    "approval_required": "*" in policy["approval_operations"]
                    or f"{node_type}.{operation}" in policy["approval_operations"],
                    "lookup_tool": "lookup_credential_options"}
        operations = search_operations(operation_catalog(row.credential_type, node_type), query)
        offset = max(0, offset)
        return {"operations": operations[offset:offset + 30], "total": len(operations),
                "approval_operations": policy["approval_operations"],
                "next_offset": offset + 30 if len(operations) > offset + 30 else None}

    async def call_credential_operation(self, credential_id, node_type, operation, arguments):
        from nodes.core.run_op import run_node_operation

        row = await self._credential(credential_id)
        operation_tool(row.credential_type, node_type, operation)
        return await run_node_operation(
            node_type=node_type, operation=operation, arguments=arguments,
            credential_id=row.id, user_id=self.user_id, pool=self.pool,
            organization_id=self.organization_id, conversation_id=self.conversation_id,
            approval_context=self.continuation,
            operation_context=self.continuation,
        )

    async def require_credential_approval(self, credential_id, operations):
        from repositories.credential_approvals import CredentialApprovalRepo
        row = await self._credential(credential_id)
        allowed = {op["key"] for op in operation_catalog(row.credential_type)} | {"*"}
        if not operations or set(operations) - allowed:
            raise ValueError("Select operation keys from credential_operations, or '*' for all operations.")
        restrictions = await CredentialApprovalRepo(self.pool).tighten(
            row.id, self.user_id, operations,
        )
        # Tightening has already completed; it is not a pending human request.
        # Only the explicit review tool returns a link and registers a continuation.
        return {"approval_operations": restrictions}

    async def request_credential_permissions(self, credential_id):
        from repositories.credential_approvals import CredentialApprovalRepo
        from mcp_adapter.auth.endpoints import get_frontend_url

        row = await self._credential(credential_id)
        await CredentialApprovalRepo(self.pool).await_human_review(row.id, self.user_id, self.continuation)
        return {"settings_url": f"{get_frontend_url().rstrip('/')}/credential/permissions/{row.id}",
                "auto_resume": self.continuation is not None}

    async def lookup_credential_options(self, credential_id, node_type, operation, field, context=None,
                                        search=None, page_token=None):
        from nodes.core.run_op import run_node_lookup

        row = await self._credential(credential_id)
        _, configs = operation_tool(row.credential_type, node_type, operation)
        lookup = next((config for config in configs.values() if config["tool_type"] == "node_op_lookup"), {})
        fields = lookup.get("fields", {})
        if field not in fields:
            raise ValueError("Unknown lookup field. Read the operation's schema first.")
        return await run_node_lookup(
            node_type=node_type, field_name=fields[field], credential_id=row.id,
            user_id=self.user_id, organization_id=self.organization_id,
            pool=self.pool, context=context, search=search, page_token=page_token,
            conversation_id=self.conversation_id, approval_context=self.continuation,
        )
