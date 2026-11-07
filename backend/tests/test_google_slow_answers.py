"""A Google API that takes longer than httpx's 5-second default still answers.

With the default, a large document's fetch failed as a ReadTimeout whose text
is empty, so the agent was told nothing. The node must build its client with a
read timeout past that default; the local server answers at once, and the test
reads the timeout each client was built with rather than waiting 6 seconds.
"""

import asyncio

import httpx
import pytest

from nodes import google_docs_node
from nodes.google_docs_node import GoogleDocsGetDocumentConfig, GoogleDocsNode

pytestmark = pytest.mark.asyncio

HTTPX_DEFAULT_READ_TIMEOUT = 5.0


@pytest.fixture
async def google(monkeypatch):
    body = b'{"documentId": "doc-1", "title": "Price list", "body": {"content": []}}'

    async def answer(reader, writer):
        await reader.read(4096)
        writer.write(b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: "
                     + str(len(body)).encode() + b"\r\n\r\n" + body)
        await writer.drain()
        writer.close()

    built = []
    real_client = httpx.AsyncClient

    def client(*args, **kwargs):
        built.append(httpx.Timeout(kwargs.get("timeout", HTTPX_DEFAULT_READ_TIMEOUT)))
        return real_client(*args, **kwargs)

    server = await asyncio.start_server(answer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(google_docs_node, "GOOGLE_DOCS_API_BASE", f"http://127.0.0.1:{port}/v1/documents")
    monkeypatch.setattr(google_docs_node.httpx, "AsyncClient", client)
    try:
        yield built
    finally:
        server.close()


async def test_a_document_slower_than_five_seconds_is_fetched(google):
    node = GoogleDocsNode("docs", "automation-google-docs", {}, sio=None, sid=None)
    output = await node._get_document(GoogleDocsGetDocumentConfig(document_id="doc-1", include_content=True), "token")
    assert output["status"] == "success" and output["document"]["title"] == "Price list"
    assert google and all(timeout.read > HTTPX_DEFAULT_READ_TIMEOUT for timeout in google), google


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
