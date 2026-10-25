"""What a file at a URL holds, without fetching it (nodes/core/media_resolver.py ``describe_url``): one of NoClick's
own stored files by its record, any other by what its server answers a HEAD with. A reply's embedded file is sent
by this, never by how its URL ends."""

from types import SimpleNamespace
from urllib.parse import quote

import httpx
import pytest

from nodes.core.media_resolver import FileInfo, describe_url, read_url
from utils.resource_store import file_name, resource_key_at

OWNER, WORKFLOW, RESOURCE = ("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222",
                             "33333333-3333-3333-3333-333333333333")
KEY = f"{OWNER}/{WORKFLOW}/{RESOURCE}/Dummy PDF"


@pytest.fixture
def stored(monkeypatch):
    """This instance's files are served at files.test, and its records are a dict by id."""
    rows = {}

    class Repo:
        def __init__(self, pool):
            pass

        async def get_resource(self, resource_id):
            return rows.get(resource_id)

    monkeypatch.setattr("utils.resource_store.get_public_download_url", lambda key: "https://files.test/" + quote(key))
    monkeypatch.setattr("repositories.resources.ResourceRepo", Repo)
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: "pool")
    return rows


@pytest.fixture
def server(monkeypatch):
    """Every other host, through the guarded client's interface: answers with ``server.answer(request)``."""
    host = SimpleNamespace(seen=[], answer=None)

    def client(*, trusted_exact_urls=(), **kwargs):
        def handle(request):
            host.seen.append(request)
            return host.answer(request)

        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr("utils.ssrf.guarded_async_client", client)
    return host


def test_a_download_url_names_its_resource_only_where_this_instance_serves_it(stored):
    url = "https://files.test/" + quote(KEY)
    assert resource_key_at(url) == KEY
    assert resource_key_at("https://files.test/" + KEY) == KEY  # as a reply may carry it, the space unencoded
    assert resource_key_at("https://elsewhere.example/" + quote(KEY)) is None
    assert resource_key_at("https://files.test/other/" + quote(KEY)) is None
    assert resource_key_at("https://files.test/report.pdf") is None


@pytest.mark.asyncio
async def test_a_stored_file_is_its_record_with_the_extension_its_type_takes(stored, server):
    stored[RESOURCE] = {"storage_ref": KEY, "name": "Dummy PDF", "mime_type": "application/pdf", "size_bytes": 642}
    server.answer = lambda request: pytest.fail("a stored file is read from its record")
    assert await describe_url("https://files.test/" + quote(KEY)) == FileInfo("application/pdf", "Dummy PDF.pdf", 642)
    # A record for another key, or none, describes nothing.
    stored[RESOURCE] = {**stored[RESOURCE], "storage_ref": f"{OWNER}/account/{RESOURCE}/other.pdf"}
    assert await describe_url("https://files.test/" + quote(KEY)) is None
    del stored[RESOURCE]
    assert await describe_url("https://files.test/" + quote(KEY)) is None


@pytest.mark.asyncio
async def test_any_other_file_is_what_its_server_answers_a_head_with(stored, server):
    server.answer = lambda request: httpx.Response(200, headers={
        "content-type": "application/pdf", "content-length": "5120",
        "content-disposition": 'attachment; filename="Q3 plan.pdf"'})
    assert await describe_url("https://cdn.example/dl/9f2c") == FileInfo("application/pdf", "Q3 plan.pdf", 5120)
    assert server.seen[-1].method == "HEAD" and "NoClick" in server.seen[-1].headers["user-agent"]
    # A page served as HTML is an HTML file named for its URL.
    server.answer = lambda request: httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"})
    assert await describe_url("https://cdn.example/games/neon") == FileInfo("text/html", "neon.html", None)
    # An untyped answer is typed by the file's name; with no name that names one, nothing can tell.
    server.answer = lambda request: httpx.Response(200, headers={"content-type": "application/octet-stream"})
    assert await describe_url("https://cdn.example/b/build.zip") == FileInfo("application/zip", "build.zip", None)
    assert await describe_url("https://cdn.example/b/build") is None


@pytest.mark.asyncio
async def test_a_url_that_doesnt_answer_describes_nothing(stored, server):
    server.answer = lambda request: httpx.Response(404)
    assert await describe_url("https://cdn.example/gone.pdf") is None

    def refused(request):
        raise httpx.ConnectError("refused")

    server.answer = refused
    assert await describe_url("https://cdn.example/x.pdf") is None


@pytest.mark.asyncio
async def test_a_private_address_is_never_asked(stored, monkeypatch):
    monkeypatch.delenv("OUTBOUND_ALLOW_PRIVATE_IPS", raising=False)
    monkeypatch.delenv("HTTP_NODE_ALLOW_PRIVATE_IPS", raising=False)
    assert await describe_url("http://169.254.169.254/latest/meta-data/x.pdf") is None
    assert await describe_url("http://127.0.0.1:8000/report.pdf") is None


@pytest.mark.asyncio
async def test_a_stored_file_is_read_from_storage_and_any_other_fetched_within_its_cap(stored, server, monkeypatch):
    reads = []

    async def from_storage(bucket, key):
        reads.append((bucket, key))
        return b"%PDF-1.4 dummy", "application/pdf"

    monkeypatch.setattr("utils.r2_cloudflare.download_bytes_from_r2_async_native", from_storage)
    monkeypatch.setattr("utils.ssrf.assert_url_allowed", _allowed)
    assert await read_url("https://files.test/" + quote(KEY), max_bytes=1000) == b"%PDF-1.4 dummy"
    assert reads == [("workflow-resources", KEY)]
    with pytest.raises(ValueError, match="too large"):
        await read_url("https://files.test/" + quote(KEY), max_bytes=10)
    server.answer = lambda request: httpx.Response(200, content=b"<p>page</p>", headers={"content-type": "text/html"})
    assert await read_url("https://cdn.example/page.html", max_bytes=1000) == b"<p>page</p>"
    assert server.seen[-1].method == "GET"
    with pytest.raises(ValueError, match="limit"):
        await read_url("https://cdn.example/page.html", max_bytes=4)


async def _allowed(url):
    return None


@pytest.mark.parametrize("name, mime, source, named", [
    ("Dummy PDF", "application/pdf", "", "Dummy PDF.pdf"),
    ("Neon Static latest source files", "application/zip", "/workspace/neon.zip", "Neon Static latest source files.zip"),
    ("game", "text/html", "/tmp/game.html", "game.html"),
    ("notes", "text/plain", "/tmp/notes.md", "notes.md"),  # the source's own extension wins over the type's
    ("Report v1.2", "application/pdf", "", "Report v1.2.pdf"),
    ("photo.jpeg", "image/jpeg", "", "photo.jpeg"), ("Game.HTML", "text/html", "", "Game.HTML"),
    ("blob", "application/octet-stream", "", "blob"),  # a type that names nothing adds nothing
])
def test_a_file_name_ends_in_the_extension_of_what_it_holds(name, mime, source, named):
    assert file_name(name, mime, source=source) == named
