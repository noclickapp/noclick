"""A Google API that takes longer than httpx's 5-second default still answers.

With the default, a large document's fetch failed as a ReadTimeout whose text
is empty, so the agent was told nothing. The server here is local and answers
after 6 seconds.
"""

import asyncio

import pytest

from nodes import google_docs_node
from nodes.google_docs_node import GoogleDocsGetDocumentConfig, GoogleDocsNode

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def slow_google(monkeypatch):
    body = b'{"documentId": "doc-1", "title": "Price list", "body": {"content": []}}'

    async def answer(reader, writer):
        await reader.read(4096)
        await asyncio.sleep(6)
        writer.write(b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: "
                     + str(len(body)).encode() + b"\r\n\r\n" + body)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(answer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(google_docs_node, "GOOGLE_DOCS_API_BASE", f"http://127.0.0.1:{port}/v1/documents")
    try:
        yield
    finally:
        server.close()


async def test_a_document_slower_than_five_seconds_is_fetched(slow_google):
    node = GoogleDocsNode("docs", "automation-google-docs", {}, sio=None, sid=None)
    output = await node._get_document(GoogleDocsGetDocumentConfig(document_id="doc-1", include_content=True), "token")
    assert output["status"] == "success" and output["document"]["title"] == "Price list"


async def test_an_empty_tool_error_is_named_by_its_type(monkeypatch):
    import httpx
    from nodes.agent import tool_execution

    class Node:
        user_id = workflow_id = execution_id = node_id = None

    async def times_out(*args, **kwargs):
        raise httpx.ReadTimeout("")

    monkeypatch.setattr(tool_execution, "_execute_workflow_tool", times_out)
    result = await tool_execution.execute_tool(Node(), "docs__fetch", {}, {"docs__fetch": {"tool_type": "workflow"}})
    assert result == {"success": False, "error": "ReadTimeout"}
