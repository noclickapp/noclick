"""Every SDK agent gets upload_file — parity with the CLI harnesses.

CLI harnesses inject a sandbox-keyed upload_file shadow tool unconditionally
(cloud/agent/runtime/cli_shadow.py); the SDK path used to gate its synthesized
upload_file on a FilesystemNode or a repo mount, leaving a bare SDK agent —
which still has execute_bash and a lazy sandbox — with no way to publish files
it creates. The synthesis is now unconditional, with a wired FilesystemNode's
own tool definition taking precedence.
"""

from nodes.agent_node import AgentNode
from nodes.filesystem_node import UPLOAD_FILE_TOOL_NAME, get_upload_tool_definition
from tests.test_builder_requests import USER, builder_request_db  # noqa: F401


def _bare_agent() -> AgentNode:
    agent = object.__new__(AgentNode)
    agent.node_id = "agent-1"
    agent._workflow_nodes = []
    agent._workflow_edges = []
    return agent


def test_bare_sdk_agent_gets_upload_file():
    """No FilesystemNode, no mounts, no tools at all — upload_file is still
    on the belt, matching the CLI harnesses' unconditional shadow injection."""
    tool_params, tool_configs, _ = _bare_agent()._collect_tool_definitions({})

    assert UPLOAD_FILE_TOOL_NAME in tool_configs
    assert tool_configs[UPLOAD_FILE_TOOL_NAME]["tool_type"] == "filesystem"
    names = [p["function"]["name"] for p in tool_params]
    assert UPLOAD_FILE_TOOL_NAME in names


def test_wired_filesystem_node_definition_wins():
    """A FilesystemNode's own upload_file must not be clobbered or duplicated
    by the synthesized fallback — the config keeps the filesystem node's id,
    not the agent's."""
    agent = _bare_agent()
    agent._workflow_edges = [
        {"source": "fs-1", "target": "agent-1", "targetHandle": "bottom"}
    ]
    inputs = {"fs-1": {"type": "tool_definition", **get_upload_tool_definition()}}

    tool_params, tool_configs, _ = agent._collect_tool_definitions(inputs)

    assert tool_configs[UPLOAD_FILE_TOOL_NAME]["node_id"] == "fs-1"
    names = [p["function"]["name"] for p in tool_params]
    assert names.count(UPLOAD_FILE_TOOL_NAME) == 1


async def test_an_upload_named_without_its_extension_keeps_its_files(monkeypatch):
    """``upload_file`` with ``name="Dummy PDF"`` once stored a PDF named "Dummy PDF": its download named no type and a
    chat could only send it as a link. The name takes the source file's extension."""
    from types import SimpleNamespace

    from nodes.agent.tool_execution import _execute_filesystem_tool

    stored = []

    async def store(**kwargs):
        stored.append(kwargs)
        return {"download_url": "https://files.test/x", "resource_id": "r1", "name": kwargs["filename"],
                "size_bytes": len(kwargs["body"]), "mime_type": kwargs["content_type"]}

    class Pool:
        async def fetchrow(self, *args):
            return None

    async def read_file(path):
        return b"%PDF-1.4"

    monkeypatch.setattr("utils.resource_store.create_resource_from_bytes", store)
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: Pool())
    node = SimpleNamespace(_active_agent=SimpleNamespace(_runtime=SimpleNamespace(read_file=read_file)),
                           workflow_id="wf", user_id="u", node_id="n", conversation_id="ck:wf:n:k")
    made = await _execute_filesystem_tool(node, "upload_file", {"file_path": "/tmp/dummy.pdf", "name": "Dummy PDF"}, {})
    assert made["name"] == "Dummy PDF.pdf" and made["mime_type"] == "application/pdf"
    # Uploading sends it to no one; the result says so, with the words that would.
    assert "nobody has it yet" in made["message"] and "![Dummy PDF.pdf](https://files.test/x)" in made["message"]
    assert (stored[0]["filename"], stored[0]["content_type"]) == ("Dummy PDF.pdf", "application/pdf")
    await _execute_filesystem_tool(node, "upload_file", {"file_path": "/workspace/game.html", "name": "game.html"}, {})
    assert stored[1]["filename"] == "game.html"  # a name that has its extension is kept as it is


async def test_the_same_file_uploaded_again_is_the_resource_it_already_is(builder_request_db, monkeypatch):
    """An agent that sent one picture in two turns uploaded it in each, and each upload stored another copy under a
    new link. The same bytes under the same name are the workflow's resource already; changed bytes or another name
    are a new one. Over PostgreSQL, with only the object store's PUT replaced."""
    from types import SimpleNamespace

    from nodes.agent.tool_execution import _execute_filesystem_tool
    from utils import resource_store

    pool, _, workflow_id, _ = builder_request_db
    files = {"/workspace/panda.png": b"\x89PNG first", "/workspace/copy.png": b"\x89PNG first"}
    puts = []

    async def put(*, bucket, key, body, content_type):
        puts.append(key)

    async def read_file(path):
        return files[path]

    monkeypatch.setattr(resource_store, "upload_bytes_to_r2_async", put)
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: pool)
    node = SimpleNamespace(_active_agent=SimpleNamespace(_runtime=SimpleNamespace(read_file=read_file)),
                           workflow_id=workflow_id, user_id=USER, node_id="agent", conversation_id="ck:wf:agent:k")

    async def upload(path):
        made = await _execute_filesystem_tool(node, "upload_file", {"file_path": path}, {})
        assert made["success"] is True
        return made

    first = await upload("/workspace/panda.png")
    again = await upload("/workspace/panda.png")
    assert (again["resource_id"], again["url"], again["name"]) == (first["resource_id"], first["url"], "panda.png")
    assert len(puts) == 1

    files["/workspace/panda.png"] = b"\x89PNG edited"
    edited = await upload("/workspace/panda.png")
    renamed = await upload("/workspace/copy.png")
    assert len({first["resource_id"], edited["resource_id"], renamed["resource_id"]}) == 3 and len(puts) == 3
    assert await pool.fetchval("SELECT count(*) FROM workflow_resources WHERE workflow_id = $1::uuid",
                               workflow_id) == 3
