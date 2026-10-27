"""An SVG drawn as a PNG (``utils.svg_image``), with the real renderer: what a phone's chat gets in place of an SVG,
which WhatsApp sends as a text file of its code."""

from io import BytesIO

import pytest
from PIL import Image

from utils import svg_image

TITLE = ('<text x="20" y="40" font-size="28" font-family="Arial,sans-serif" fill="#111">Bitcoin 2026</text>')


def _svg(width, height, body=""):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">{body}</svg>'.encode()


def _drawn(svg: bytes) -> Image.Image:
    return Image.open(BytesIO(svg_image.to_png(svg, width=1080, height=2160))).convert("RGB")


def test_it_fills_the_width_a_chat_shows_keeping_its_shape():
    assert _drawn(_svg(500, 280)).size == (1080, 605)
    assert _drawn(_svg(4000, 2000)).size == (1080, 540)
    # A tall one fits the height instead.
    assert _drawn(_svg(100, 4320)).size == (50, 2160)


def test_its_text_is_drawn_on_white():
    """A chat shows a transparent picture's background black, and with no font a chart's labels vanish unseen."""
    picture = _drawn(_svg(500, 280, TITLE))
    assert picture.getpixel((1070, 595)) == (255, 255, 255)
    title = picture.crop((40, 40, 500, 100)).convert("L")
    assert title.getextrema()[0] < 100


@pytest.mark.parametrize("svg", [b"not an svg", b"\xff\xfe<svg", b"<svg"])
def test_what_isnt_an_svg_it_can_draw_is_refused(svg):
    with pytest.raises(ValueError):
        svg_image.to_png(svg, width=1080, height=2160)


@pytest.mark.parametrize("family", ["Arial,sans-serif", "Helvetica", "Times New Roman", "monospace", None])
def test_text_is_drawn_whichever_family_it_names(family):
    """A Linux server has none of resvg's own fallback fonts, and there a chart's every label was left out."""
    named = f' font-family="{family}"' if family else ""
    picture = _drawn(_svg(500, 280, f'<text x="20" y="40" font-size="28"{named}>Bitcoin 2026</text>'))
    assert picture.crop((40, 40, 500, 100)).convert("L").getextrema()[0] < 100


def test_text_with_no_font_installed_is_refused_rather_than_left_out(monkeypatch):
    monkeypatch.setattr(svg_image, "_draws_text", lambda families: False)
    svg_image._families.cache_clear()
    try:
        with pytest.raises(ValueError, match="no font is installed"):
            svg_image.to_png(_svg(500, 280, TITLE), width=1080, height=2160)
        # Without text there's nothing to leave out.
        assert svg_image.to_png(_svg(500, 280), width=1080, height=2160).startswith(b"\x89PNG")
    finally:
        svg_image._families.cache_clear()
