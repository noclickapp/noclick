"""
Concise, high-quality tests for MockHTTPServer.

Tests DNS patching to intercept requests to arbitrary domains and validates
compatibility with multiple HTTP client libraries.
"""

import pytest
import pytest_asyncio
import json
from tests.mocks.mock_server import MockHTTPServer, SyncMockHTTPServer, MockRequest, MockResponse


@pytest_asyncio.fixture
async def mock_server():
    """Async mock server fixture."""
    server = MockHTTPServer(port=8080)
    async with server:
        yield server


@pytest.fixture
def sync_mock_server():
    """Sync mock server fixture."""
    server = SyncMockHTTPServer(port=8081)
    with server:
        yield server


# ===== Core Functionality Tests =====

@pytest.mark.asyncio
async def test_basic_requests(mock_server):
    """Test basic GET/POST requests."""
    import httpx

    # Test GET
    mock_server.add_handler('*', '/test', lambda req: MockResponse(body=b'GET OK'))
    async with httpx.AsyncClient() as client:
        r = await client.get('http://localhost:8080/test')
        assert r.status_code == 200
        assert r.content == b'GET OK'

    # Test POST with JSON
    def post_handler(req: MockRequest) -> MockResponse:
        data = json.loads(req.body)
        return MockResponse(body=json.dumps({'echo': data}).encode(), headers={'content-type': 'application/json'})

    mock_server.add_handler('*', '/echo', post_handler)
    async with httpx.AsyncClient() as client:
        r = await client.post('http://localhost:8080/echo', json={'test': 123})
        assert r.status_code == 200
        assert r.json()['echo']['test'] == 123


@pytest.mark.asyncio
async def test_request_properties(mock_server):
    """Test that request properties are correctly captured."""
    def verify_handler(req: MockRequest) -> MockResponse:
        assert req.method == 'POST'
        assert req.path == '/api/test'
        assert req.headers['Authorization'] == 'Bearer token'
        assert req.query['param'] == 'value'
        assert req.body == b'body content'
        return MockResponse()

    mock_server.add_handler('*', '/api/test', verify_handler)

    import httpx
    async with httpx.AsyncClient() as client:
        await client.post(
            'http://localhost:8080/api/test?param=value',
            headers={'Authorization': 'Bearer token'},
            content=b'body content'
        )


# ===== DNS Patching Tests (Arbitrary Domains) =====

def test_dns_patching_with_requests(sync_mock_server):
    """Test DNS patching intercepts arbitrary domains with requests library."""
    import requests

    sync_mock_server.add_handler('api.example.com', '/data',
                                  lambda req: MockResponse(body=b'intercepted example.com'))
    sync_mock_server.add_handler('api.test.org', '/users',
                                  lambda req: MockResponse(body=b'intercepted test.org'))

    # Make requests to arbitrary domains - should be intercepted
    with sync_mock_server.patch_dns():
        r1 = requests.get('http://api.example.com/data')
        r2 = requests.get('http://api.test.org/users')

    assert r1.status_code == 200
    assert r1.content == b'intercepted example.com'
    assert r2.status_code == 200
    assert r2.content == b'intercepted test.org'


def test_dns_patching_with_urllib(sync_mock_server):
    """Test DNS patching intercepts arbitrary domains with urllib."""
    import urllib.request

    sync_mock_server.add_handler('github.com', '/api/repos',
                                  lambda req: MockResponse(body=b'intercepted github'))

    with sync_mock_server.patch_dns():
        with urllib.request.urlopen('http://github.com/api/repos') as response:
            data = response.read()

    assert data == b'intercepted github'


def test_dns_patching_https_arbitrary_domain():
    """Test DNS patching with HTTPS for arbitrary domains."""
    import requests

    # Create HTTPS mock server
    server = SyncMockHTTPServer(port=8444, ssl_enabled=True)
    server.add_handler('secure.example.com', '/api/data',
                       lambda req: MockResponse(body=b'intercepted HTTPS example.com'))

    with server:
        # Make HTTPS request to arbitrary domain with DNS patching
        with server.patch_dns():
            # Disable SSL verification for self-signed cert
            response = requests.get('https://secure.example.com/api/data', verify=False)

    assert response.status_code == 200
    assert response.content == b'intercepted HTTPS example.com'


# NOTE: httpx/httpcore use anyio which bypasses socket.getaddrinfo, so DNS patching
# doesn't work with httpx. For httpx, use Host header routing or connect directly to localhost.


# ===== HTTPS Support Tests =====

@pytest.mark.asyncio
async def test_https_support():
    """Test HTTPS server with self-signed certificate."""
    import httpx

    server = MockHTTPServer(port=8443, ssl_enabled=True)
    server.add_handler('*', '/secure', lambda req: MockResponse(body=b'HTTPS works!'))

    async with server:
        # Disable SSL verification for self-signed cert
        async with httpx.AsyncClient(verify=False) as client:
            r = await client.get('https://localhost:8443/secure')
            assert r.status_code == 200
            assert r.content == b'HTTPS works!'


def test_https_sync():
    """Test HTTPS with synchronous requests library."""
    import requests

    server = SyncMockHTTPServer(port=8444, ssl_enabled=True)
    server.add_handler('*', '/secure', lambda req: MockResponse(body=b'Sync HTTPS!'))

    with server:
        # Disable SSL verification
        r = requests.get('https://localhost:8444/secure', verify=False)
        assert r.status_code == 200
        assert r.content == b'Sync HTTPS!'


# ===== HTTP Client Compatibility Tests =====

def test_requests_library(sync_mock_server):
    """Test with requests library."""
    import requests
    sync_mock_server.add_handler('*', '/test', lambda req: MockResponse(body=b'requests OK'))
    r = requests.get('http://localhost:8081/test')
    assert r.content == b'requests OK'


def test_urllib_library(sync_mock_server):
    """Test with urllib (stdlib)."""
    import urllib.request
    sync_mock_server.add_handler('*', '/test', lambda req: MockResponse(body=b'urllib OK'))
    with urllib.request.urlopen('http://localhost:8081/test') as r:
        assert r.read() == b'urllib OK'


@pytest.mark.asyncio
async def test_aiohttp_library(mock_server):
    """Test with aiohttp library."""
    import aiohttp
    mock_server.add_handler('*', '/test', lambda req: MockResponse(body=b'aiohttp OK'))
    async with aiohttp.ClientSession() as session:
        async with session.get('http://localhost:8080/test') as r:
            assert await r.read() == b'aiohttp OK'


# ===== Advanced Features =====

@pytest.mark.asyncio
async def test_default_handler(mock_server):
    """Test default handler for unmatched paths."""
    import httpx
    mock_server.set_default_handler(lambda req: MockResponse(body=f"Caught: {req.path}".encode()))
    async with httpx.AsyncClient() as client:
        r = await client.get('http://localhost:8080/any/random/path')
        assert b'Caught: /any/random/path' in r.content


@pytest.mark.asyncio
async def test_concurrent_requests(mock_server):
    """Test handling multiple concurrent requests."""
    import httpx
    import asyncio

    count = [0]

    def counter(req: MockRequest) -> MockResponse:
        count[0] += 1
        return MockResponse(body=f"Request #{count[0]}".encode())

    mock_server.add_handler('*', '/count', counter)

    async with httpx.AsyncClient() as client:
        tasks = [client.get('http://localhost:8080/count') for _ in range(10)]
        responses = await asyncio.gather(*tasks)
        assert all(r.status_code == 200 for r in responses)
        assert count[0] == 10


@pytest.mark.asyncio
async def test_handler_exception_returns_500(mock_server):
    """Test that handler exceptions return 500."""
    import httpx
    mock_server.add_handler('*', '/error', lambda req: 1/0)  # Intentional error
    async with httpx.AsyncClient() as client:
        r = await client.get('http://localhost:8080/error')
        assert r.status_code == 500


# ===== MCP Protocol Simulation =====

@pytest.mark.asyncio
async def test_mcp_protocol_simulation(mock_server):
    """Test simulating MCP protocol with JSONRPC."""
    import httpx

    def mcp_handler(req: MockRequest) -> MockResponse:
        data = json.loads(req.body)
        method = data.get('method')

        if method == 'initialize':
            result = {
                'jsonrpc': '2.0',
                'id': data['id'],
                'result': {'protocolVersion': '2024-11-05', 'serverInfo': {'name': 'test'}}
            }
        elif method == 'tools/list':
            result = {
                'jsonrpc': '2.0',
                'id': data['id'],
                'result': {'tools': [{'name': 'tool1'}, {'name': 'tool2'}]}
            }
        else:
            result = {'jsonrpc': '2.0', 'id': data['id'], 'error': {'code': -32601, 'message': 'Method not found'}}

        return MockResponse(body=json.dumps(result).encode(), headers={'content-type': 'application/json'})

    mock_server.add_handler('*', '/mcp', mcp_handler)

    async with httpx.AsyncClient() as client:
        # Test initialize
        r1 = await client.post('http://localhost:8080/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'})
        assert r1.json()['result']['protocolVersion'] == '2024-11-05'

        # Test tools/list
        r2 = await client.post('http://localhost:8080/mcp', json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
        assert len(r2.json()['result']['tools']) == 2


# ===== Host-Specific Routing =====

@pytest.mark.asyncio
async def test_host_specific_handlers(mock_server):
    """Test that handlers can be host-specific using Host header."""
    import httpx

    # Register host-specific handlers
    mock_server.add_handler('api.example.com', '/data', lambda req: MockResponse(body=b'example data'))
    mock_server.add_handler('api.test.com', '/data', lambda req: MockResponse(body=b'test data'))

    # Test by setting Host header (simulates domain-specific routing)
    async with httpx.AsyncClient() as client:
        r1 = await client.get('http://localhost:8080/data', headers={'Host': 'api.example.com'})
        r2 = await client.get('http://localhost:8080/data', headers={'Host': 'api.test.com'})

        assert r1.content == b'example data'
        assert r2.content == b'test data'


# ===== Streaming HTTP Tests =====

@pytest.mark.asyncio
async def test_sse_streaming(mock_server):
    """Test Server-Sent Events (SSE) streaming."""
    import httpx
    import asyncio

    async def sse_stream():
        for i in range(3):
            yield f"data: event {i}\n\n".encode()
            await asyncio.sleep(0.01)

    mock_server.add_handler('*', '/events', lambda req: MockResponse(
        stream=sse_stream,
        headers={'content-type': 'text/event-stream', 'cache-control': 'no-cache'}
    ))

    async with httpx.AsyncClient() as client:
        async with client.stream('GET', 'http://localhost:8080/events') as response:
            assert response.status_code == 200
            assert response.headers['content-type'] == 'text/event-stream'

            chunks = []
            async for chunk in response.aiter_bytes():
                chunks.append(chunk)

            # Verify we got all 3 events
            assert len(chunks) == 3
            assert chunks[0] == b'data: event 0\n\n'
            assert chunks[1] == b'data: event 1\n\n'
            assert chunks[2] == b'data: event 2\n\n'


@pytest.mark.asyncio
async def test_chunked_streaming(mock_server):
    """Test chunked transfer encoding with progressive streaming."""
    import httpx
    import asyncio

    async def chunked_stream():
        data = b"This is a long response that will be streamed in chunks"
        chunk_size = 10
        for i in range(0, len(data), chunk_size):
            yield data[i:i+chunk_size]
            await asyncio.sleep(0.01)

    mock_server.add_handler('*', '/stream', lambda req: MockResponse(
        stream=chunked_stream,
        headers={'content-type': 'text/plain'}
    ))

    async with httpx.AsyncClient() as client:
        async with client.stream('GET', 'http://localhost:8080/stream') as response:
            assert response.status_code == 200

            # Collect all chunks
            full_data = b''
            async for chunk in response.aiter_bytes():
                full_data += chunk

            assert full_data == b"This is a long response that will be streamed in chunks"


@pytest.mark.asyncio
async def test_streaming_with_aiohttp(mock_server):
    """Test streaming with aiohttp client."""
    import aiohttp
    import asyncio

    async def stream_generator():
        for i in range(5):
            yield f"Line {i}\n".encode()
            await asyncio.sleep(0.01)

    mock_server.add_handler('*', '/lines', lambda req: MockResponse(
        stream=stream_generator,
        headers={'content-type': 'text/plain'}
    ))

    async with aiohttp.ClientSession() as session:
        async with session.get('http://localhost:8080/lines') as response:
            assert response.status == 200

            lines = []
            async for line in response.content:
                lines.append(line)

            assert len(lines) == 5
            assert lines[0] == b'Line 0\n'
            assert lines[4] == b'Line 4\n'


def test_streaming_sync(sync_mock_server):
    """Test streaming with synchronous requests library."""
    import requests
    import asyncio

    # Define sync stream generator wrapper
    async def async_generator():
        for i in range(3):
            yield f"Chunk {i}\n".encode()
            await asyncio.sleep(0.01)

    sync_mock_server.server.add_handler('*', '/sync-stream', lambda req: MockResponse(
        stream=async_generator,
        headers={'content-type': 'text/plain'}
    ))

    response = requests.get('http://localhost:8081/sync-stream', stream=True)
    assert response.status_code == 200

    chunks = list(response.iter_content(chunk_size=None))
    assert len(chunks) == 3
    assert chunks[0] == b'Chunk 0\n'
    assert chunks[2] == b'Chunk 2\n'
