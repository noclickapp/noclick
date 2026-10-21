"""The SDK agent sees an image named in its message as the image itself (``extract_inline_image_urls``): a stored
file's URL counts whatever its extension, except one whose name says it's something else, which a turn would only
fetch to throw away (a voice note's .caf held each iMessage voice turn up by a fetch)."""

import pytest

from nodes.agent.handlers import _media_utils
from nodes.agent.handlers._media_utils import extract_inline_image_urls

ASSETS = "https://assets.example"


@pytest.fixture(autouse=True)
def assets(monkeypatch):
    monkeypatch.setattr("utils.hosted_defaults.assets_base_url", lambda: ASSETS)
    _media_utils._asset_url_re.cache_clear()
    yield
    _media_utils._asset_url_re.cache_clear()


def test_a_stored_image_and_an_image_link_are_seen():
    message = (f"[Image; attachment_id=a1]\nFile: {ASSETS}/u/account/a1/photo\n"
               "and https://example.com/menu.png, please")
    assert extract_inline_image_urls(message) == ["https://example.com/menu.png", f"{ASSETS}/u/account/a1/photo"]


@pytest.mark.parametrize("name", ["note.caf", "note.ogg", "note.m4a", "menu.pdf", "clip.mp4", "call.amr"])
def test_a_stored_file_named_as_something_else_is_left_alone(name):
    assert extract_inline_image_urls(f"[Voice note; attachment_id=a2]\nFile: {ASSETS}/u/account/a2/{name}") == []
