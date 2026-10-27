"""An SVG drawn as a PNG (resvg), for where an SVG isn't shown as a picture: a phone's chat apps, which send one as a
file of its source (``coder/coordinator/texting``)."""

from __future__ import annotations

import functools
from io import BytesIO
from typing import Dict

import resvg_py
from PIL import Image

# The fonts text falls back to (every family the SVG names that isn't installed, and text that names none): resvg's
# own are a Mac's (Times New Roman, Arial), which a Linux server lacks, and there it left a chart's every label out
# without a word. DejaVu where it's installed (the server images install it), else resvg's.
DEJAVU = {"font_family": "DejaVu Sans", "serif_family": "DejaVu Serif", "sans_serif_family": "DejaVu Sans",
          "monospace_family": "DejaVu Sans Mono"}
_TEXT_PROBE = ('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'
               '<text x="2" y="16" font-size="16">Aa</text></svg>')


def _draws_text(families: Dict[str, str]) -> bool:
    png = bytes(resvg_py.svg_to_bytes(svg_string=_TEXT_PROBE, background="white", **families))
    return Image.open(BytesIO(png)).convert("L").getextrema()[0] < 255


@functools.cache
def _families() -> Dict[str, str]:
    for families in (DEJAVU, {}):
        if _draws_text(families):
            return families
    raise ValueError("no font is installed to draw its text")


def to_png(svg: bytes, *, width: int, height: int) -> bytes:
    """``svg`` drawn as a PNG that fits ``width`` × ``height``, scaled up or down to it and keeping its shape, on
    white: a chat shows a transparent picture's background black. Raises ValueError when it isn't an SVG resvg can
    draw, or it has text and no font is installed to draw it in."""
    try:
        markup = svg.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("it isn't SVG text") from exc
    families = _families() if "<text" in markup else {}
    return bytes(resvg_py.svg_to_bytes(svg_string=markup, width=width, height=height, background="white",
                                       **families))
