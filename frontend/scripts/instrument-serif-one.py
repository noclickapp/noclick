"""Makes public/fonts/instrument-serif-one-400-{normal,italic}.woff2: Instrument Serif's "1" with a flag that reads as
a 1. Its own flag is almost flat, so "1¢" and "$1" read as "l¢" and "$l" at display sizes, and the font has no numeral
alternates (its only features are ccmp, liga and locl). Same stem, foot and advance; only the flag is redrawn. The font
is under the SIL OFL 1.1 with no reserved name, so these stay under it (the name table keeps its copyright).

    python3 frontend/scripts/instrument-serif-one.py   # from the repo root, with fonttools and brotli installed
"""
from pathlib import Path

from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont

FRONTEND = Path(__file__).resolve().parent.parent
SOURCE = FRONTEND / 'node_modules/@fontsource/instrument-serif/files'
OUT = FRONTEND / 'public/fonts'


def upright(pen):
    pen.moveTo((20, 0))
    pen.qCurveTo((5, 0), (5, 11))
    pen.qCurveTo((5, 22), (18, 23))
    pen.lineTo((57, 27))
    pen.qCurveTo((78, 29), (93, 45), (93, 66))
    pen.lineTo((93, 628))  # the stem's left, up to the flag's foot
    pen.lineTo((24, 572))  # the flag's lower edge, down to the left
    pen.qCurveTo((10, 562), (5, 575))  # its tip
    pen.qCurveTo((3, 588), (14, 598))
    pen.lineTo((113, 726))  # its upper edge, back up to the stem's top
    pen.qCurveTo((122, 735), (136, 735))
    pen.qCurveTo((157, 735), (157, 713))
    pen.lineTo((157, 66))
    pen.qCurveTo((157, 45), (172, 29), (193, 27))
    pen.lineTo((226, 23))
    pen.qCurveTo((239, 22), (239, 11))
    pen.qCurveTo((239, 0), (224, 0))
    pen.closePath()


def italic(pen):
    pen.moveTo((-35, 0))
    pen.qCurveTo((-50, 0), (-50, 10))
    pen.qCurveTo((-50, 22), (-35, 23))
    pen.lineTo((5, 27))
    pen.qCurveTo((27, 29), (46, 45), (50, 66))
    pen.lineTo((180, 628))  # the upright flag, sheared along the italic's stem
    pen.lineTo((98, 572))
    pen.qCurveTo((81, 562), (79, 575))
    pen.qCurveTo((80, 588), (94, 598))
    pen.lineTo((222, 726))
    pen.qCurveTo((233, 735), (246, 735))
    pen.qCurveTo((266, 735), (262, 713))
    pen.lineTo((112, 66))
    pen.qCurveTo((108, 45), (119, 29), (139, 27))
    pen.lineTo((170, 23))
    pen.qCurveTo((182, 22), (182, 12))
    pen.qCurveTo((182, 0), (164, 0))
    pen.closePath()


def make(style, draw):
    font = TTFont(SOURCE / f'instrument-serif-latin-400-{style}.woff2')
    pen = TTGlyphPen(font.getGlyphSet())
    draw(pen)
    font['glyf']['one'] = pen.glyph()
    font['hmtx']['one'] = (font['hmtx']['one'][0], font['glyf']['one'].xMin if hasattr(font['glyf']['one'], 'xMin') else 0)
    options = Options()
    options.flavor = 'woff2'
    options.layout_features = []
    options.notdef_outline = True
    options.name_IDs = ['*']
    subsetter = Subsetter(options)
    subsetter.populate(unicodes=[0x31])
    subsetter.subset(font)
    font.flavor = 'woff2'
    font.save(OUT / f'instrument-serif-one-400-{style}.woff2')


make('normal', upright)
make('italic', italic)
