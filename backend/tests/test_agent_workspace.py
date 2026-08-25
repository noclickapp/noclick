"""Agent workspace file view — workspace-source resolution (mirrors the
sandbox's mount decision), capability-token integrity, and the streaming
route's auth gate.
"""
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nodes.filesystem_node import get_volume_name as fs_volume_name
from utils.access_control import AccessResult, Permission
from utils.agent_workspace import (
    file_url_path,
    mint_file_token,
    resolve_workspace_source,
    verify_file_token,
)
from utils.capabilities import WORKSPACE_VOLUME, capability
from utils.volume_backend import workspace_volume_name


WF = "wf-1"
AGENT = "agent_1"
CK = "__interface_chat__"


def _expected_workspace_volume(workflow_id: str, node_id: str, ck: str) -> str:
    """Use the registered hosted namer when present and the public local namer
    otherwise, mirroring resolve_workspace_source without importing cloud code."""
    workspace = capability(WORKSPACE_VOLUME)
    if workspace is not None:
        return workspace.volume_name_for("ws", workflow_id, node_id, ck)
    return workspace_volume_name(workflow_id, node_id, ck)


class _FakePool:
    class _Acquire:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args):
            return None

    def acquire(self):
        return self._Acquire()


class TestResolveWorkspaceSource:
    def test_conversation_gets_per_ck_workspace(self):
        s = resolve_workspace_source(WF, AGENT, CK, [], [])
        assert s is not None
        assert s.mount_path == "/workspace"
        assert s.volume_name == _expected_workspace_volume(WF, AGENT, CK)

    def test_ck_less_run_has_no_workspace(self):
        assert resolve_workspace_source(WF, AGENT, None, [], []) is None

    def test_wired_filesystem_node_is_the_workspace(self):
        nodes = [{"id": "fs1", "type": "filesystem",
                  "config": {"volume_mode": "common", "mount_path": "/data"}}]
        edges = [{"source": "fs1", "target": AGENT, "targetHandle": "bottom"}]
        s = resolve_workspace_source(WF, AGENT, CK, nodes, edges)
        assert s.mount_path == "/data"
        assert s.volume_name == fs_volume_name(WF, "fs1", "common", CK)

    def test_filesystem_per_ck_mode_keys_volume_on_ck(self):
        nodes = [{"id": "fs1", "type": "filesystem",
                  "config": {"volume_mode": "per_conversation_key"}}]
        edges = [{"source": "fs1", "target": AGENT, "targetHandle": "bottom"}]
        s = resolve_workspace_source(WF, AGENT, CK, nodes, edges)
        assert s.volume_name == fs_volume_name(WF, "fs1", "per_conversation_key", CK)
        assert s.mount_path == "/workspace"

    def test_edge_matching_replicates_runtime_provider_scoping(self):
        # The panel must resolve the volume the SANDBOX mounts, so the edge
        # match replicates AgentNode._is_wired_tool_provider exactly:
        # source/target keys + targetHandle == "bottom". Shapes the runtime
        # rejects (non-bottom handle, sourceId-only conventions) fall back to
        # the per-CK workspace — the same volume the sandbox would mount.
        nodes = [{"id": "fs1", "type": "filesystem",
                  "data": {"config": {"volume_mode": "common"}}}]
        for edges in (
            [{"sourceId": "fs1", "targetId": AGENT}],                 # sourceId convention
            [{"source": "fs1", "target": AGENT}],                     # no handle
            [{"source": "fs1", "target": AGENT, "targetHandle": "left"}],  # dataflow handle
        ):
            s = resolve_workspace_source(WF, AGENT, CK, nodes, edges)
            assert s.volume_name == _expected_workspace_volume(WF, AGENT, CK), edges

    def test_unrelated_edges_ignored(self):
        nodes = [{"id": "fs1", "type": "filesystem", "config": {}},
                 {"id": "sheets1", "type": "google-sheets", "config": {}}]
        edges = [
            {"source": "fs1", "target": "other_agent", "targetHandle": "bottom"},
            {"source": "sheets1", "target": AGENT, "targetHandle": "bottom"},
        ]
        s = resolve_workspace_source(WF, AGENT, CK, nodes, edges)
        assert s.volume_name == _expected_workspace_volume(WF, AGENT, CK)


class TestFileTokens:
    def test_round_trip(self):
        token = mint_file_token("vol-a", "/seo/report.md")
        assert verify_file_token(token) == {"vol": "vol-a", "path": "/seo/report.md"}

    def test_expired_token_rejected(self):
        token = mint_file_token("vol-a", "/x", ttl_seconds=-5)
        assert verify_file_token(token) is None

    def test_tampered_token_rejected(self):
        token = mint_file_token("vol-a", "/x")
        assert verify_file_token(token[:-4] + "AAAA") is None
        assert verify_file_token("") is None

    def test_wrong_audience_rejected(self):
        import jwt

        from mcp_adapter.auth.tokens import get_mcp_signing_key

        foreign = jwt.encode(
            {"aud": "noclick-mcp", "exp": int(time.time()) + 300,
             "vol": "vol-a", "path": "/x"},
            get_mcp_signing_key(), algorithm="HS256",
        )
        assert verify_file_token(foreign) is None

    def test_url_path_embeds_token(self):
        url = file_url_path("vol-a", "/seo/report.md")
        assert url.startswith("/agent/workspace/file?token=")
        token = url.split("token=", 1)[1]
        from urllib.parse import unquote

        assert verify_file_token(unquote(token)) == {"vol": "vol-a", "path": "/seo/report.md"}


class TestStreamingRouteAuth:
    def _client(self) -> TestClient:
        from utils.agent_workspace_routes import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_missing_or_invalid_token_403(self):
        client = self._client()
        assert client.get("/agent/workspace/file").status_code == 403
        assert client.get("/agent/workspace/file?token=garbage").status_code == 403

    def test_expired_token_403(self):
        client = self._client()
        token = mint_file_token("vol-a", "/x", ttl_seconds=-5)
        assert client.get(f"/agent/workspace/file?token={token}").status_code == 403

    def test_preflight_cors(self):
        res = self._client().options("/agent/workspace/file")
        assert res.status_code == 204
        assert res.headers["Access-Control-Allow-Origin"] == "*"

    def test_svg_is_served_as_text_never_inline_svg(self):
        # image/svg+xml served inline renders as a DOCUMENT and executes
        # embedded scripts — agent-authored-markup XSS. svg must ride the
        # text/plain rule like .html/.xml.
        from utils.agent_workspace_routes import _content_type

        assert _content_type("evil.svg") == "text/plain; charset=utf-8"
        assert _content_type("page.html") == "text/plain; charset=utf-8"
        assert _content_type("photo.png") == "image/png"

    def test_missing_file_404(self):
        from utils.volume_backend import VolumeFileNotFound

        class _FakeBackend:
            async def iter_file(self, name, path):
                raise VolumeFileNotFound(path)

        import utils.volume_backend as volume_backend

        client = self._client()
        token = mint_file_token("vol-a", "/gone.md")
        with patch.object(volume_backend, "_backend", _FakeBackend()), \
             patch.object(volume_backend, "_initialized", True):
            res = client.get(f"/agent/workspace/file?token={token}")
        assert res.status_code == 404

    def test_streams_file_with_disposition(self):
        class _FakeBackend:
            async def iter_file(self, name, path):
                async def gen():
                    yield b"# Report\n"
                    yield b"body"

                return gen()

        import utils.volume_backend as volume_backend

        client = self._client()
        token = mint_file_token("vol-a", "/seo/report.md")
        with patch.object(volume_backend, "_backend", _FakeBackend()), \
             patch.object(volume_backend, "_initialized", True):
            inline = client.get(f"/agent/workspace/file?token={token}")
            download = client.get(f"/agent/workspace/file?token={token}&dl=1")
        assert inline.status_code == 200
        assert inline.content == b"# Report\nbody"
        # Inline previews are text/plain so agent-authored markup can't execute.
        assert inline.headers["content-type"].startswith("text/plain")
        assert "inline" in inline.headers["content-disposition"]
        assert download.headers["content-type"] == "application/octet-stream"
        assert "attachment" in download.headers["content-disposition"]


class TestUploadTokens:
    def test_round_trip(self):
        from utils.agent_workspace import mint_upload_token, verify_upload_token

        assert verify_upload_token(mint_upload_token("vol-a")) == "vol-a"

    def test_expired_token_rejected(self):
        from utils.agent_workspace import mint_upload_token, verify_upload_token

        assert verify_upload_token(mint_upload_token("vol-a", ttl_seconds=-5)) is None

    def test_default_upload_token_is_short_lived(self):
        import jwt

        from mcp_adapter.auth.tokens import get_mcp_signing_key
        from utils.agent_workspace import (
            FILE_TOKEN_TTL_SECONDS,
            UPLOAD_TOKEN_TTL_SECONDS,
            WORKSPACE_UPLOAD_AUDIENCE,
            mint_upload_token,
        )

        now = int(time.time())
        claims = jwt.decode(
            mint_upload_token("vol-a"),
            get_mcp_signing_key(),
            algorithms=["HS256"],
            audience=WORKSPACE_UPLOAD_AUDIENCE,
        )
        assert 0 < claims["exp"] - now <= UPLOAD_TOKEN_TTL_SECONDS
        assert UPLOAD_TOKEN_TTL_SECONDS < FILE_TOKEN_TTL_SECONDS

    def test_read_token_never_authorizes_upload(self):
        # Audience separation: a (widely shared) file-read link must not become
        # a write capability, and an upload token must not read files.
        from utils.agent_workspace import mint_upload_token, verify_upload_token

        assert verify_upload_token(mint_file_token("vol-a", "/x")) is None
        assert verify_file_token(mint_upload_token("vol-a")) is None

    def test_url_path_embeds_token(self):
        from urllib.parse import unquote

        from utils.agent_workspace import upload_url_path, verify_upload_token

        url = upload_url_path("vol-a")
        assert url.startswith("/agent/workspace/upload?token=")
        assert verify_upload_token(unquote(url.split("token=", 1)[1])) == "vol-a"


class TestUploadRoute:
    def _client(self) -> TestClient:
        from utils.agent_workspace_routes import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def _token(self) -> str:
        from utils.agent_workspace import mint_upload_token

        return mint_upload_token("vol-a")

    def test_missing_or_invalid_token_403(self):
        client = self._client()
        assert client.post("/agent/workspace/upload?path=a.txt", content=b"x").status_code == 403
        assert client.post(
            "/agent/workspace/upload?token=garbage&path=a.txt", content=b"x"
        ).status_code == 403

    def test_path_traversal_rejected(self):
        client = self._client()
        for bad in ("", ".", "..", "../etc/passwd", "a/../../b", "%2e%2e%2fescape"):
            res = client.post(
                f"/agent/workspace/upload?token={self._token()}&path={bad}", content=b"x"
            )
            assert res.status_code == 400, bad

    def test_writes_through_volume_backend(self):
        import utils.volume_backend as volume_backend

        written = {}

        class _FakeBackend:
            async def write_file(self, name, path, data):
                written[(name, path)] = data

        client = self._client()
        with patch.object(volume_backend, "_backend", _FakeBackend()), \
             patch.object(volume_backend, "_initialized", True):
            res = client.post(
                f"/agent/workspace/upload?token={self._token()}&path=/docs/spec.md",
                content=b"hello",
            )
            # Messy-but-safe paths normalize instead of erroring.
            normalized = client.post(
                f"/agent/workspace/upload?token={self._token()}&path=a//./b.txt",
                content=b"n",
            )
        assert res.status_code == 200
        assert res.json() == {"success": True, "path": "docs/spec.md"}
        assert normalized.status_code == 200
        assert normalized.json()["path"] == "a/b.txt"
        assert written == {
            ("vol-a", "docs/spec.md"): b"hello",
            ("vol-a", "a/b.txt"): b"n",
        }

    def test_oversize_upload_413(self):
        from utils import agent_workspace_routes

        client = self._client()
        with patch.object(agent_workspace_routes, "MAX_UPLOAD_BYTES", 4):
            res = client.post(
                f"/agent/workspace/upload?token={self._token()}&path=a.bin",
                content=b"12345",
            )
        assert res.status_code == 413

    def test_declared_oversize_upload_is_rejected_before_streaming(self):
        from utils import agent_workspace_routes

        client = self._client()
        with patch.object(agent_workspace_routes, "MAX_UPLOAD_BYTES", 4), \
             patch.object(agent_workspace_routes.Request, "stream") as stream:
            res = client.post(
                f"/agent/workspace/upload?token={self._token()}&path=a.bin",
                content=b"12345",
                headers={"Content-Length": "5"},
            )
        assert res.status_code == 413
        stream.assert_not_called()

    def test_backend_failure_502(self):
        import utils.volume_backend as volume_backend

        class _FailingBackend:
            async def write_file(self, name, path, data):
                raise RuntimeError("volume unavailable")

        client = self._client()
        with patch.object(volume_backend, "_backend", _FailingBackend()), \
             patch.object(volume_backend, "_initialized", True):
            res = client.post(
                f"/agent/workspace/upload?token={self._token()}&path=a.txt", content=b"x"
            )
        assert res.status_code == 502


class TestLocalBackendWriteFile:
    def test_write_creates_dirs_and_lists(self, tmp_path, monkeypatch):
        import asyncio

        from utils.volume_backend import LocalVolumeBackend

        monkeypatch.setenv("NOCLICK_HOME", str(tmp_path))
        backend = LocalVolumeBackend()
        asyncio.run(backend.write_file("vol-x", "docs/spec.md", b"hello"))
        listing = asyncio.run(backend.list_files("vol-x"))
        assert listing["exists"]
        assert [f["path"] for f in listing["files"]] == ["docs/spec.md"]
        assert (tmp_path / "volumes" / "vol-x" / "docs" / "spec.md").read_bytes() == b"hello"

    def test_write_refuses_escape(self, tmp_path, monkeypatch):
        import asyncio

        import pytest

        from utils.volume_backend import LocalVolumeBackend

        monkeypatch.setenv("NOCLICK_HOME", str(tmp_path))
        with pytest.raises(ValueError):
            asyncio.run(LocalVolumeBackend().write_file("vol-x", "../escape.txt", b"x"))


class TestFileBrowserLoadValue:
    @pytest.mark.parametrize(
        ("permission", "can_upload"),
        [
            (Permission.VIEW, False),
            (Permission.EDIT, True),
            (Permission.OWNER, True),
        ],
    )
    def test_listing_only_gives_editors_upload_capability(self, permission, can_upload):
        import asyncio

        import utils.volume_backend as volume_backend
        from nodes.filesystem_node import FilesystemNode
        from utils.agent_workspace import verify_upload_token

        class _FakeBackend:
            async def list_entries(self, name, path="/"):
                return {"exists": True, "entries": [{"path": "a.txt", "type": "file"}]}

        wf = uuid.uuid4()
        with patch.object(volume_backend, "_backend", _FakeBackend()), \
             patch.object(volume_backend, "_initialized", True), \
             patch(
                 "utils.access_control.check_resource_access",
                 new=AsyncMock(return_value=AccessResult(True, permission, "test")),
             ):
            result = asyncio.run(FilesystemNode.load_field_value(
                field_name="file_browser", user_id="u1", workflow_id=wf,
                node_id="fs1", pool=_FakePool(),
            ))
        value = result["value"]
        assert value["files"] == [{"path": "a.txt", "type": "file"}]
        assert ("upload_url_path" in value) is can_upload
        if not can_upload:
            return
        token = value["upload_url_path"].split("token=", 1)[1]
        from urllib.parse import unquote

        assert verify_upload_token(unquote(token)) == fs_volume_name(str(wf), "fs1", "common", None)


class TestWorkspaceHandlerUploadPermission:
    @pytest.mark.parametrize(
        ("permission", "can_upload"),
        [
            (Permission.VIEW, False),
            (Permission.EDIT, True),
            (Permission.OWNER, True),
        ],
    )
    @pytest.mark.asyncio
    async def test_listing_only_gives_editors_upload_capability(
        self, permission, can_upload
    ):
        from utils.agent_workspace import WorkspaceSource
        from wss.handlers.agent_workspace_handler import AgentWorkspaceHandler

        class _Sio:
            async def get_session(self, _sid):
                return {"user_id": "u1"}

        handler = AgentWorkspaceHandler(_Sio())
        handler.get_pool = AsyncMock(return_value=_FakePool())
        handler._respond = AsyncMock()
        request = SimpleNamespace(
            request_id="req-1",
            workflow_id=str(uuid.uuid4()),
            node_id="agent-1",
            conversation_key="chat-1",
        )

        with patch(
            "wss.handlers.agent_workspace_handler.check_resource_access",
            new=AsyncMock(return_value=AccessResult(True, permission, "test")),
        ), patch(
            "wss.handlers.agent_workspace_handler.WorkflowRepo.get_workflow_org_and_data",
            new=AsyncMock(return_value={"workflow": {"nodes": [], "edges": []}}),
        ), patch(
            "wss.handlers.agent_workspace_handler.resolve_workspace_source",
            return_value=WorkspaceSource("vol-a", "/workspace"),
        ), patch(
            "wss.handlers.agent_workspace_handler.list_workspace_files",
            new=AsyncMock(return_value={
                "exists": True, "truncated": False, "files": [],
            }),
        ), patch(
            "wss.handlers.agent_workspace_handler.upload_url_path",
            return_value="/agent/workspace/upload?token=signed",
        ) as mint:
            await handler.list_files("sid-1", request)

        response = handler._respond.await_args.kwargs
        assert response["success"] is True
        assert ("upload_url_path" in response) is can_upload
        assert mint.call_count == int(can_upload)


class TestMountPathCanonicalization:
    """Relative mount paths are canonicalized before a sandbox receives them;
    invalid paths are rejected at configuration time."""

    def _parse(self, raw):
        from nodes.filesystem_node import FilesystemConfig

        return FilesystemConfig.model_validate({"mount_path": raw}).mount_path

    def test_relative_path_gains_leading_slash(self):
        assert self._parse("assets") == "/assets"
        assert self._parse("data/files") == "/data/files"

    def test_noise_normalizes(self):
        assert self._parse("/data/") == "/data"
        assert self._parse("  /x  ") == "/x"
        assert self._parse("a//b/./c") == "/a/b/c"
        # ".." resolves against root (POSIX): never escapes, always canonical.
        assert self._parse("../x") == "/x"
        assert self._parse("/a/../b") == "/b"

    def test_empty_falls_back_to_default(self):
        assert self._parse("") == "/workspace"
        assert self._parse("   ") == "/workspace"

    def test_root_rejected(self):
        import pytest

        # Everything ".."-shaped canonicalizes to "/" — mounting over the
        # sandbox root is the one unfixable input.
        for bad in ("/", "..", "/..", "/a/../.."):
            with pytest.raises(ValueError):
                self._parse(bad)

    def test_runtime_view_agrees(self):
        # The runtime lens and direct parse must land on the same canonical
        # path — build-time verdicts may not diverge from run-time behavior.
        from nodes.core.base import runtime_config_view
        from nodes.filesystem_node import FilesystemConfig

        for raw, want in (("assets", "/assets"), ("", "/workspace")):
            view = runtime_config_view({"mount_path": raw}, FilesystemConfig)
            assert FilesystemConfig.model_validate(view).mount_path == want


