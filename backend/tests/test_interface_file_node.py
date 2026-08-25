# Tests for the universal interface File node (nodes/interface/file_node.py).
# The File node replaced the separate image/audio/video/pdf interface nodes, so
# these tests pin the media-type detection (MIME precedence + extension fallback +
# edge cases) and the execute() output contract (src path, resource_id path, and
# file_name derivation) that the frontend FileBlock trusts to pick a viewer.

import pytest

from nodes.interface.file_node import (
    FileInterfaceNode,
    FileInterfaceNodeConfig,
    FileConfig,
    _detect_media_type,
)


def _node(**config_kwargs) -> FileInterfaceNode:
    """Build a File node with sio=None (emit() no-ops) for pure execute() tests."""
    return FileInterfaceNode(
        node_id="file-1",
        node_type="interface-file",
        node_data={},
        config=FileInterfaceNodeConfig(config=FileConfig(**config_kwargs)),
    )


# --------------------------------------------------------------------------- #
# _detect_media_type — MIME takes precedence over the extension                #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "mime,expected",
    [
        ("image/png", "image"),
        ("image/jpeg", "image"),
        ("audio/mpeg", "audio"),
        ("audio/wav", "audio"),
        ("video/mp4", "video"),
        ("video/webm", "video"),
        ("application/pdf", "pdf"),
        ("IMAGE/PNG", "image"),  # case-insensitive
    ],
)
def test_detect_by_mime(mime, expected):
    assert _detect_media_type(mime, "whatever.bin") == expected


def test_mime_overrides_conflicting_extension():
    # A .mp4 name but an image MIME must resolve to image (MIME is authoritative).
    assert _detect_media_type("image/png", "photo.mp4") == "image"
    # ...and an image extension but a video MIME resolves to video.
    assert _detect_media_type("video/mp4", "clip.png") == "video"


# --------------------------------------------------------------------------- #
# _detect_media_type — extension fallback when MIME is absent                  #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "name,expected",
    [
        ("a.png", "image"), ("a.jpg", "image"), ("a.jpeg", "image"),
        ("a.gif", "image"), ("a.webp", "image"), ("a.svg", "image"), ("a.bmp", "image"), ("a.avif", "image"),
        ("a.mp3", "audio"), ("a.wav", "audio"), ("a.ogg", "audio"), ("a.m4a", "audio"),
        ("a.aac", "audio"), ("a.flac", "audio"), ("a.opus", "audio"),
        ("a.mp4", "video"), ("a.webm", "video"), ("a.mov", "video"),
        ("a.mkv", "video"), ("a.avi", "video"),
        ("a.pdf", "pdf"),
    ],
)
def test_detect_by_extension(name, expected):
    assert _detect_media_type(None, name) == expected
    assert _detect_media_type("", name) == expected  # empty MIME also falls through


def test_extension_case_insensitive():
    assert _detect_media_type(None, "PHOTO.PNG") == "image"
    assert _detect_media_type(None, "Clip.MP4") == "video"


@pytest.mark.parametrize(
    "name",
    ["report.docx", "data.csv", "archive.zip", "installer.exe", "notes.txt", "noext"],
)
def test_unknown_extension_is_generic_file(name):
    assert _detect_media_type(None, name) == "file"


def test_query_string_and_fragment_are_stripped_before_extension():
    assert _detect_media_type(None, "https://cdn.x.io/a.png?token=abc&x=1") == "image"
    assert _detect_media_type(None, "https://cdn.x.io/a.pdf#page=2") == "pdf"
    assert _detect_media_type(None, "https://cdn.x.io/a.mp4?sig=z#t") == "video"


def test_empty_inputs_default_to_file():
    assert _detect_media_type(None, None) == "file"
    assert _detect_media_type("", "") == "file"
    assert _detect_media_type(None, "") == "file"


def test_dotted_path_without_real_extension():
    # A dot in a directory segment but a bare final segment → no extension → file.
    assert _detect_media_type(None, "https://x.io/v1.2/download") == "file"


# --------------------------------------------------------------------------- #
# execute() — direct src / URL path (no DB)                                    #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_execute_src_url_derives_type_and_filename():
    node = _node(src="https://cdn.x.io/photo.png")
    out = await node.execute({})
    assert out == {
        "url": "https://cdn.x.io/photo.png",
        "src": "https://cdn.x.io/photo.png",
        "type": "image",
        "file_name": "photo.png",
        "mime_type": None,
    }


@pytest.mark.asyncio
async def test_execute_url_with_query_derives_clean_filename():
    node = _node(src="https://cdn.x.io/report.pdf?token=xyz")
    out = await node.execute({})
    assert out["type"] == "pdf"
    assert out["file_name"] == "report.pdf"  # query stripped from basename


@pytest.mark.asyncio
async def test_execute_inputs_value_overrides_config_src():
    node = _node(src="https://cdn.x.io/default.png")
    out = await node.execute({"value": "https://cdn.x.io/song.mp3"})
    assert out["url"] == "https://cdn.x.io/song.mp3"
    assert out["src"] == "https://cdn.x.io/song.mp3"
    assert out["type"] == "audio"


@pytest.mark.asyncio
async def test_execute_inputs_src_key_also_honored():
    node = _node()
    out = await node.execute({"src": "https://cdn.x.io/clip.mov"})
    assert out["url"] == "https://cdn.x.io/clip.mov"
    assert out["type"] == "video"


@pytest.mark.asyncio
async def test_execute_explicit_filename_not_overwritten():
    node = _node(src="https://cdn.x.io/a1b2c3.png", file_name="Vacation Photo.png")
    out = await node.execute({})
    assert out["file_name"] == "Vacation Photo.png"


@pytest.mark.asyncio
async def test_execute_empty_config_is_generic_file():
    node = _node()
    out = await node.execute({})
    assert out["url"] == ""
    assert out["file_name"] == ""
    assert out["type"] == "file"
    assert out["mime_type"] is None


@pytest.mark.asyncio
async def test_execute_unknown_type_url_is_download_card():
    node = _node(src="https://cdn.x.io/data.csv")
    out = await node.execute({})
    assert out["type"] == "file"
    assert out["file_name"] == "data.csv"


# --------------------------------------------------------------------------- #
# execute() — uploaded resource_id path (DB + R2 resolution mocked)           #
# --------------------------------------------------------------------------- #

class _FakePool:
    def __init__(self, row):
        self._row = row

    async def fetchrow(self, *_args, **_kwargs):
        return self._row


@pytest.mark.asyncio
async def test_execute_resource_id_resolves_public_url_and_mime(monkeypatch):
    row = {
        "storage_ref": "owner/wf/res/photo.heic",
        "mime_type": "image/heic",
        "name": "photo.heic",
    }
    monkeypatch.setattr(
        "utils.database_pool.get_native_pool", lambda: _FakePool(row)
    )
    monkeypatch.setattr(
        "utils.r2_cloudflare.get_public_download_url",
        lambda ref: f"https://assets.example.test/{ref}",
    )
    node = _node(resource_id="res-123")
    out = await node.execute({})
    assert out["url"] == "https://assets.example.test/owner/wf/res/photo.heic"
    assert out["src"] == out["url"]
    assert out["mime_type"] == "image/heic"
    # .heic isn't in the extension table, but the stored MIME resolves it to image.
    assert out["type"] == "image"
    assert out["file_name"] == "photo.heic"


@pytest.mark.asyncio
async def test_execute_resource_id_missing_row_falls_back_to_src(monkeypatch):
    # Confirmed-absent resource → keep the config src (no crash, no phantom URL).
    monkeypatch.setattr(
        "utils.database_pool.get_native_pool", lambda: _FakePool(None)
    )
    node = _node(resource_id="gone", src="https://cdn.x.io/fallback.pdf")
    out = await node.execute({})
    assert out["url"] == "https://cdn.x.io/fallback.pdf"
    assert out["type"] == "pdf"


@pytest.mark.asyncio
async def test_execute_resource_mime_overrides_generic_extension(monkeypatch):
    # storage_ref has a generic .bin ext but the stored MIME says it's audio.
    row = {
        "storage_ref": "owner/wf/res/voice.bin",
        "mime_type": "audio/ogg",
        "name": "voice-note.bin",
    }
    monkeypatch.setattr(
        "utils.database_pool.get_native_pool", lambda: _FakePool(row)
    )
    monkeypatch.setattr(
        "utils.r2_cloudflare.get_public_download_url",
        lambda ref: f"https://assets.example.test/{ref}",
    )
    node = _node(resource_id="res-9")
    out = await node.execute({})
    assert out["type"] == "audio"
    assert out["mime_type"] == "audio/ogg"
    assert out["file_name"] == "voice-note.bin"


@pytest.mark.asyncio
async def test_execute_output_always_has_full_contract():
    # Every execute() output must carry the five keys the FileBlock reads.
    node = _node(src="https://cdn.x.io/x.webp")
    out = await node.execute({})
    assert set(out.keys()) == {"url", "src", "type", "file_name", "mime_type"}
