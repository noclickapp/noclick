"""Adapt serialized SDK traffic to the harness's single contract handler."""
from contextlib import contextmanager
from io import BytesIO
from unittest.mock import patch

import asyncio
import aiohttp
import h11
import httpx
from aiohttp.client_proto import ResponseHandler
from aiohttp.connector import Connection
from botocore.awsrequest import AWSResponse
from botocore.httpsession import URLLib3Session
from urllib3.response import HTTPResponse


class _MemoryTransport(asyncio.Transport):
    """A byte sink for aiohttp's real HTTP serializer; never opens a socket."""

    def __init__(self, protocol):
        super().__init__()
        self.protocol = protocol
        self.data = bytearray()
        self.closed = False

    def write(self, data):
        self.data.extend(data)

    def is_closing(self):
        return self.closed

    def close(self):
        if not self.closed:
            self.closed = True
            asyncio.get_running_loop().call_soon(self.protocol.connection_lost, None)

    abort = close


@contextmanager
def intercept_http(handler):
    """Keep client serialization, signing and parsing; replace only network I/O.

    Botocore prepares and signs AWSPreparedRequest before calling send. Reading
    its body here also captures file-like and aws-chunked payloads as transmitted,
    rather than substituting the SDK's pre-serialization operation arguments.
    The same handler validates all clients and selects/validates their responses.
    Unhandled clients remain subject to the harness's socket/DNS denial.
    """
    original_client = httpx.AsyncClient
    original_aiohttp_send = aiohttp.ClientRequest.send

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        kwargs["trust_env"] = False
        return original_client(*args, **kwargs)

    def aws_send(self, request):
        body = request.body
        if hasattr(body, "read"):
            body = body.read()
        captured = httpx.Request(
            request.method,
            request.url,
            headers=list(request.headers.items()),
            content=body,
            extensions={"conformance_transport": "botocore"},
        )
        response = handler(captured)
        # A real urllib3 response supports both AWSResponse.content's stream()
        # and StreamingBody.read()/close(), without bypassing SDK parsing.
        raw = HTTPResponse(
            body=BytesIO(response.content),
            status=response.status_code,
            headers=dict(response.headers),
            preload_content=False,
            decode_content=False,
        )
        return AWSResponse(
            request.url, response.status_code, dict(response.headers), raw
        )

    async def aiohttp_connect(self, request, traces, timeout):
        protocol = ResponseHandler(asyncio.get_running_loop())
        protocol.connection_made(_MemoryTransport(protocol))
        return Connection(
            self, request.connection_key, protocol, asyncio.get_running_loop()
        )

    async def aiohttp_send(self, connection):
        # Use aiohttp's actual writer: JSON, multipart boundaries, streaming
        # payloads, compression and transfer framing are produced by the client.
        response = await original_aiohttp_send(self, connection)
        if self._continue is not None and not self._continue.done():
            # The in-memory peer accepts the provisional 100-continue handshake.
            self._continue.set_result(True)
        if self._writer is not None:
            await self._writer
        protocol = connection.protocol
        wire = h11.Connection(h11.SERVER)
        wire.receive_data(bytes(protocol.transport.data))
        body = bytearray()
        headers = None
        while True:
            event = wire.next_event()
            if isinstance(event, h11.Request):
                headers = list(event.headers)
            elif isinstance(event, h11.Data):
                body.extend(event.data)
            elif isinstance(event, h11.EndOfMessage):
                break
            else:
                raise ValueError("Incomplete aiohttp request serialization")
        captured = httpx.Request(
            self.method,
            str(self.url),
            headers=headers,
            content=bytes(body),
            extensions={"conformance_transport": "aiohttp"},
        )
        answer = handler(captured)
        # Feed the selected bytes through aiohttp's real response parser too.
        # h11 supplies HTTP transfer framing, leaving content encodings intact.
        encoded = wire.send(
            h11.Response(
                status_code=answer.status_code,
                headers=list(answer.headers.raw),
            )
        )
        encoded += wire.send(h11.Data(data=answer.content))
        encoded += wire.send(h11.EndOfMessage())
        protocol.data_received(encoded)
        return response

    with patch("httpx.AsyncClient", client), patch.object(
        URLLib3Session, "send", aws_send
    ), patch.object(aiohttp.TCPConnector, "connect", aiohttp_connect), patch.object(
        aiohttp.ClientRequest, "send", aiohttp_send
    ):
        yield
