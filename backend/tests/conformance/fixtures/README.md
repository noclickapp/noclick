# Synthetic file inputs

These are local, synthetic schema witnesses, not provider-authored examples.
They contain no identities or secrets. They are read unchanged at runtime; no
file-generation package or external process runs in the harness.

| File | Contents | Generated once with |
| --- | --- | --- |
| minimal.pdf | One blank 72 × 72 point page, complete cross-reference table | `pypdf.PdfWriter().add_blank_page(width=72, height=72)` then `write` |
| minimal.png | One transparent RGBA pixel | PNG signature, IHDR (1 × 1, depth 8, color 6), zlib-compressed scanline, IEND; every chunk has its CRC |
| minimal.wav | 0.1 seconds of silent mono PCM, 8 kHz, 16 bits | Python `wave`, 800 zero samples |
| minimal.mp3 | Silent MPEG 2.5 Layer III frames, 8 kHz, 8 kbps | `ffmpeg -i minimal.wav -map_metadata -1 -codec:a libmp3lame -b:a 8k -write_xing 0 -id3v2_version 0 minimal.mp3` |
| minimal.txt | `Conformance.` and a newline | UTF-8 literal |

`test_files.py` parses the PDF strictly with pypdf, checks every PNG chunk CRC
and decompresses its pixel, reads the WAV with the standard library, walks every
complete MP3 frame, and decodes the text as UTF-8. Each kind is also exercised
through real Pydantic config validation and the existing OpenAPI request path,
including malformed-base64 and wrong-MIME rejection controls.

# Fixture catalog

`catalog/` is a catalog in the format `CONFORMANCE_CATALOG` reads, for a
made-up API (`api.fixture.example`) that describes no real provider, and the
node `test_catalog_provider.py` defines for it. Its manifest pins
`fixture.yaml` by sha256, so edit the spec and its hash together.
