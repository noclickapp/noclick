"""Dependency-free PDF builders for tests.

Hand-assembled minimal PDFs (with a correct xref table) so tests exercising
the content-extraction pipeline don't need a PDF-authoring library — pypdf
(a real runtime dep) parses these fine.
"""

import io


def text_pdf(text: str = "Invoice #1 total $10") -> bytes:
    """A single-page PDF whose text layer contains ``text``.

    ``text`` must not contain unescaped parentheses or backslashes — keep
    fixture strings simple.
    """
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj".encode() + body + b"endobj\n")
    xref_pos = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer<</Size {len(objs) + 1}/Root 1 0 R>>\nstartxref\n{xref_pos}\n%%EOF".encode()
    )
    return out.getvalue()


def blank_pdf(pages: int = 1) -> bytes:
    """A PDF with no text layer — the scanned-document stand-in."""
    import pypdf

    w = pypdf.PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=612, height=792)
    b = io.BytesIO()
    w.write(b)
    return b.getvalue()
