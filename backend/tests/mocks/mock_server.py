"""
Simple mock HTTP server for testing.

Intercepts HTTP requests to ANY domain (not just localhost) by patching DNS
resolution. Works with ANY HTTP client library.

Usage:
    server = MockHTTPServer(port=8080)
    server.add_handler('example.com', '/api', lambda req: MockResponse(body=b'OK'))

    with server.patch_dns():
        # Requests to example.com will hit our mock server
        response = requests.get('https://example.com/api')
"""

import asyncio
import inspect
import json
import logging
import socket
import ssl
import tempfile
import ipaddress
from pathlib import Path
from typing import Dict, Callable, Optional, Any, Tuple
from dataclasses import dataclass, field
from aiohttp import web
import threading
from unittest.mock import patch
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@dataclass
class MockRequest:
    """Request object passed to handlers."""
    method: str
    path: str
    host: str
    headers: Dict[str, str]
    body: bytes
    query: Dict[str, str]


@dataclass
class MockResponse:
    """Response object returned by handlers."""
    status: int = 200
    body: bytes = b''
    headers: Dict[str, str] = field(default_factory=dict)
    stream: Optional[Callable] = None  # Async generator for streaming responses


class MockHTTPServer:
    """
    Mock HTTP/HTTPS server that intercepts requests to arbitrary domains.

    Binds to a real port and patches DNS resolution to redirect any domain
    to localhost, allowing seamless interception of HTTP/HTTPS requests.
    """

    def __init__(self, host: str = 'localhost', port: int = 8080, ssl_enabled: bool = False):
        self.host = host
        self.port = port
        self.ssl_enabled = ssl_enabled
        self.handlers: Dict[Tuple[str, str], Callable] = {}  # (host, path) -> handler
        self.default_handler: Optional[Callable] = None
        self.app = None
        self.runner = None
        self.site = None
        self._original_getaddrinfo = socket.getaddrinfo
        self._dns_patch = None
        self._ssl_context = None
        self._cert_file = None
        self._key_file = None

    def add_handler(self, host: str, path: str, handler: Callable[[MockRequest], MockResponse]):
        """
        Register handler for specific host and path.

        Args:
            host: Domain name (e.g., 'example.com', 'api.github.com')
            path: URL path (e.g., '/api/test')
            handler: Callable that takes MockRequest and returns MockResponse
        """
        self.handlers[(host, path)] = handler
        logger.debug(f"[MockServer] Registered: {host}{path}")

    def set_default_handler(self, handler: Callable[[MockRequest], MockResponse]):
        """Set fallback handler for unmatched requests."""
        self.default_handler = handler

    def _patched_getaddrinfo(self, host, port, family=0, type=0, proto=0, flags=0):
        """Patched DNS resolver - redirects all hosts to localhost."""
        # For our mock server's host, use original resolution
        if host == self.host:
            return self._original_getaddrinfo(host, port, family, type, proto, flags)

        # Redirect everything else to localhost on our mock server's port
        logger.debug(f"[MockServer DNS] Redirecting {host}:{port} -> localhost:{self.port}")

        # Get localhost resolution with original port, then modify the address tuples
        results = self._original_getaddrinfo('localhost', port, family, type, proto, flags)

        # Modify each result tuple to use our mock server's port
        patched_results = []
        for family, type, proto, canonname, sockaddr in results:
            # sockaddr is (host, port) for IPv4 or (host, port, flowinfo, scopeid) for IPv6
            if len(sockaddr) == 2:
                # IPv4
                patched_sockaddr = ('127.0.0.1', self.port)
            else:
                # IPv6
                patched_sockaddr = ('::1', self.port, sockaddr[2], sockaddr[3])

            patched_results.append((family, type, proto, canonname, patched_sockaddr))

        return patched_results

    def _generate_self_signed_cert(self):
        """Generate self-signed SSL certificate for testing."""
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        import datetime

        # Generate private key
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        # Generate certificate
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Test"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Test"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test"),
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ])

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=1))
            .add_extension(
                x509.SubjectAlternativeName([
                    x509.DNSName("localhost"),
                    x509.DNSName("*.localhost"),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                ]),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )

        # Write to temporary files
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.pem') as cert_file:
            cert_file.write(cert.public_bytes(serialization.Encoding.PEM))
            self._cert_file = cert_file.name

        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.key') as key_file:
            key_file.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))
            self._key_file = key_file.name

        logger.debug(f"[MockServer] Generated self-signed cert: {self._cert_file}")

    @contextmanager
    def patch_dns(self):
        """Context manager to patch DNS resolution."""
        with patch('socket.getaddrinfo', self._patched_getaddrinfo):
            yield

    async def _handle_request(self, request: web.Request) -> web.Response:
        """Internal request handler."""
        body = await request.read()

        # Extract host from Host header (includes port for non-standard ports)
        host_header = request.headers.get('Host', self.host)
        # Remove port if present
        host = host_header.split(':')[0]

        mock_req = MockRequest(
            method=request.method,
            path=request.path,
            host=host,
            headers=dict(request.headers),
            body=body,
            query=dict(request.query)
        )

        logger.debug(f"[MockServer] {mock_req.method} {host}{mock_req.path}")

        # Find handler by (host, path) or just path
        handler = self.handlers.get((host, mock_req.path))
        if not handler:
            # Try without host
            handler = self.handlers.get(('*', mock_req.path))
        if not handler:
            handler = self.default_handler

        if not handler:
            logger.warning(f"[MockServer] No handler for {host}{mock_req.path}")
            return web.Response(status=404, text="Not Found")

        try:
            # Support both sync and async handlers
            mock_resp = handler(mock_req)
            if inspect.iscoroutine(mock_resp):
                mock_resp = await mock_resp

            # Handle streaming responses (SSE, chunked transfer, etc.)
            if mock_resp.stream:
                logger.debug(f"[MockServer] Starting streaming response")
                response = web.StreamResponse(
                    status=mock_resp.status,
                    headers=mock_resp.headers
                )
                await response.prepare(request)

                # Stream data from the generator
                async for chunk in mock_resp.stream():
                    await response.write(chunk)

                await response.write_eof()
                return response

            # Regular response
            return web.Response(
                status=mock_resp.status,
                body=mock_resp.body,
                headers=mock_resp.headers
            )
        except Exception as e:
            logger.error(f"[MockServer] Handler error: {e}", exc_info=True)
            return web.Response(status=500, text=f"Handler error: {str(e)}")

    async def start(self):
        """Start server."""
        protocol = "https" if self.ssl_enabled else "http"
        logger.info(f"[MockServer] Starting on {protocol}://{self.host}:{self.port}")

        self.app = web.Application()
        self.app.router.add_route('*', '/{path:.*}', self._handle_request)

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        # Configure SSL if enabled
        if self.ssl_enabled:
            self._generate_self_signed_cert()
            self._ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            self._ssl_context.load_cert_chain(self._cert_file, self._key_file)
            self.site = web.TCPSite(self.runner, self.host, self.port, ssl_context=self._ssl_context)
        else:
            self.site = web.TCPSite(self.runner, self.host, self.port)

        await self.site.start()

        logger.info(f"[MockServer] Running on {protocol}://{self.host}:{self.port}")

    async def stop(self):
        """Stop server."""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()

        # Clean up SSL cert files
        if self._cert_file:
            try:
                Path(self._cert_file).unlink()
            except:
                pass
        if self._key_file:
            try:
                Path(self._key_file).unlink()
            except:
                pass

        logger.info(f"[MockServer] Stopped")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()


class SyncMockHTTPServer:
    """Synchronous wrapper for MockHTTPServer."""

    def __init__(self, host: str = 'localhost', port: int = 8080, ssl_enabled: bool = False):
        self.server = MockHTTPServer(host, port, ssl_enabled)
        self._thread = None
        self._loop = None
        self._started = threading.Event()
        self._stop_event = threading.Event()

    def add_handler(self, host: str, path: str, handler: Callable):
        """Register handler for host and path."""
        self.server.add_handler(host, path, handler)

    def set_default_handler(self, handler: Callable):
        """Set default handler."""
        self.server.set_default_handler(handler)

    def patch_dns(self):
        """Context manager to patch DNS."""
        return self.server.patch_dns()

    def _run_loop(self):
        """Run event loop in background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        async def run():
            await self.server.start()
            self._started.set()
            # Keep running until stop event
            while not self._stop_event.is_set():
                await asyncio.sleep(0.1)

        try:
            self._loop.run_until_complete(run())
        finally:
            self._loop.run_until_complete(self.server.stop())
            self._loop.close()

    def start(self):
        """Start server in background thread."""
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        if not self._started.wait(timeout=5.0):
            raise TimeoutError("Server start timeout")

        logger.info(f"[SyncMockServer] Started")

    def stop(self):
        """Stop server."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info(f"[SyncMockServer] Stopped")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
