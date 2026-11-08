"""Real file bytes go through the ordinary node and OpenAPI checks."""
import base64
import copy
import io
import struct
import wave
import zlib
from typing import Literal

import httpx
import pytest
from pydantic import BaseModel, Field, field_validator
from pypdf import PdfReader

from tests.conformance import harness
from tests.conformance.files import FIXTURES, ROOT, FileFixtureError
from tests.conformance.test_inputs import contract_for


def test_pdf_is_a_complete_one_page_document():
    pdf = PdfReader(ROOT / "minimal.pdf", strict=True)
    assert len(pdf.pages) == 1
    assert tuple(pdf.pages[0].mediabox) == (0, 0, 72, 72)


def test_png_has_valid_chunks_and_pixel():
    data = (ROOT / "minimal.png").read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    chunks, pos = {}, 8
    while pos < len(data):
        length, kind = struct.unpack("!I4s", data[pos : pos + 8])
        body = data[pos + 8 : pos + 8 + length]
        assert (
            zlib.crc32(kind + body)
            == struct.unpack("!I", data[pos + 8 + length : pos + 12 + length])[0]
        )
        chunks[kind] = body
        pos += length + 12
    assert pos == len(data) and chunks[b"IEND"] == b""
    assert struct.unpack("!2I5B", chunks[b"IHDR"]) == (1, 1, 8, 6, 0, 0, 0)
    assert zlib.decompress(chunks[b"IDAT"]) == b"\0\0\0\0\0"


def test_wav_is_short_pcm_and_text_is_utf8():
    with wave.open(str(ROOT / "minimal.wav")) as audio:
        assert (
            audio.getnchannels(),
            audio.getsampwidth(),
            audio.getframerate(),
            audio.getnframes(),
        ) == (1, 2, 8000, 800)
        assert len(audio.readframes(800)) == 1600
    assert (ROOT / "minimal.txt").read_text(encoding="utf-8") == "Conformance.\n"


def test_mp3_contains_complete_mpeg_layer_three_frames():
    data = (ROOT / "minimal.mp3").read_bytes()
    pos, frames = 0, 0
    while pos < len(data):
        header = int.from_bytes(data[pos : pos + 4], "big")
        assert header >> 21 == 0x7FF
        assert (header >> 19) & 3 == 0  # MPEG 2.5
        assert (header >> 17) & 3 == 1  # Layer III
        assert (header >> 12) & 15 == 1  # 8 kbps
        assert (header >> 10) & 3 == 2  # 8 kHz
        pos += 72 * 8000 // 8000 + ((header >> 9) & 1)
        frames += 1
    assert pos == len(data) and frames >= 2


def file_schema(mime, **content):
    return {
        "type": "object",
        "required": ["file_base64", "filename", "content_type"],
        "properties": {
            "file_base64": {
                "type": "string",
                "format": "byte",
                "contentMediaType": mime,
                **content,
            },
            "filename": {"type": "string", "pattern": r"^[a-z]+\.[a-z0-9]+$"},
            "content_type": {"type": "string", "enum": [mime]},
        },
    }


@pytest.mark.parametrize("mime", FIXTURES)
def test_each_kind_passes_unchanged_request_validator_and_rejects_bad_values(mime):
    schema = file_schema(mime)
    original = copy.deepcopy(schema)
    value = harness.input_sample({}, schema)
    assert (
        base64.b64decode(value["file_base64"], validate=True)
        == (ROOT / FIXTURES[mime]).read_bytes()
    )
    assert value["filename"] == FIXTURES[mime] and value["content_type"] == mime
    assert harness.sample({}, schema, examples=False, files=True) == value
    contract = contract_for(schema)
    contract.validate_request(
        httpx.Request("POST", "https://example.test/items", json=value)
    )
    for patch in (
        {"file_base64": "%%%not-base64"},
        {"content_type": "application/wrong"},
    ):
        with pytest.raises(ValueError):
            contract.validate_request(
                httpx.Request(
                    "POST", "https://example.test/items", json={**value, **patch}
                )
            )
    assert schema == original


@pytest.mark.parametrize(
    "declaration",
    [
        {"format": "byte"},
        {"contentEncoding": "base64"},
        {
            "json_schema_extra": {
                "contentEncoding": "base64",
                "contentMediaType": "application/pdf",
            }
        },
    ],
)
def test_schema_metadata_selects_base64(declaration):
    schema = {"type": "string", "contentMediaType": "application/pdf", **declaration}
    value = harness.input_sample({}, schema)
    assert len(PdfReader(io.BytesIO(base64.b64decode(value, validate=True))).pages) == 1


def test_binary_and_data_url_encodings():
    schema = {"type": "string", "contentMediaType": "image/png", "format": "binary"}
    assert harness.input_sample({}, schema) == (ROOT / "minimal.png").read_bytes()
    schema["format"] = "data-url"
    value = harness.input_sample({}, schema)
    assert value.startswith("data:image/png;base64,")
    assert (
        base64.b64decode(value.split(",", 1)[1], validate=True)
        == (ROOT / "minimal.png").read_bytes()
    )


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "string", "format": "byte"},
        {"type": "string", "format": "binary", "contentMediaType": "video/unknown"},
        {
            "type": "string",
            "contentEncoding": "base64",
            "contentMediaType": "image/png",
            "maxLength": 2,
        },
        {"type": "string", "contentEncoding": "gzip", "contentMediaType": "image/png"},
        {
            "type": "object",
            "required": ["file_base64", "filename", "content_type"],
            "properties": {
                "file_base64": {"type": "string"},
                "filename": {"const": "file.pdf"},
                "content_type": {"const": "image/png"},
            },
        },
    ],
)
def test_unknown_conflicting_and_unsupported_types_fail_closed(schema):
    with pytest.raises(FileFixtureError):
        harness.input_sample({}, schema)


def test_text_destination_and_optional_source_alternatives():
    schema = {
        "type": "object",
        "required": ["text", "name"],
        "properties": {
            "text": {
                "type": "string",
                "description": "UTF-8 literal text; name must end .txt.",
            },
            "name": {"type": "string"},
        },
    }
    assert harness.input_sample({}, schema) == {
        "text": "Conformance.\n",
        "name": "minimal.txt",
    }
    schema = {
        "type": "object",
        "properties": {
            "pdf_base64": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
            },
            "pdf_url": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
            },
            "filename": {"type": "string", "default": "document.pdf"},
        },
    }
    value = harness.sample({}, schema, examples=False, full=True, files=True)
    assert "pdf_url" not in value and value["filename"] == "document.pdf"
    assert base64.b64decode(value["pdf_base64"], validate=True).startswith(b"%PDF-")


@pytest.mark.parametrize(
    "mime", ["application/pdf", "audio/wav", "audio/mpeg", "image/png", "text/plain"]
)
async def test_generated_files_run_through_actual_config_validation(monkeypatch, mime):
    from nodes.core.registry import NODE_REGISTRY

    class Inputs(BaseModel):
        operation: Literal["upload"] = "upload"
        file_base64: str = Field(
            json_schema_extra={"contentEncoding": "base64", "contentMediaType": mime}
        )
        filename: str
        content_type: Literal[mime]

        @field_validator("file_base64")
        @classmethod
        def real_file(cls, value):
            assert (
                base64.b64decode(value, validate=True)
                == (ROOT / FIXTURES[mime]).read_bytes()
            )
            return value

    class Config(BaseModel):
        config: Inputs
        credentials: dict

    class Node:
        scope_registry = None
        get_config_model = staticmethod(lambda: Config)

        def __init__(self, config, **kwargs):
            self.config = config

        async def execute(self, _):
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://example.test/items",
                    json=self.config.config.model_dump(exclude={"operation"}),
                )
            return {"status": "success"}

    monkeypatch.setitem(NODE_REGISTRY, "synthetic", Node)
    monkeypatch.setitem(harness.PROVIDERS, "synthetic", ("synthetic", {}))
    monkeypatch.setattr(harness, "spec_entry", lambda _: (None, {}))
    monkeypatch.setattr(
        harness, "load_specs", lambda _: [contract_for(file_schema(mime)).doc]
    )
    monkeypatch.setattr(harness, "INPUTS", {})
    report = await harness.run_provider("synthetic")
    assert report["passed"] == 1 and report["fixture_errors"] == report["failed"] == 0
    for patch in ({"file_base64": "%%%"}, {"content_type": "application/wrong"}):
        invalid = await harness.run_provider(
            "synthetic", config_overrides={"upload": patch}
        )
        assert (
            invalid["fixture_errors"] == 1 and not invalid["operations"][0]["requests"]
        )


def test_enum_can_choose_supported_type_and_does_not_mutate_source():
    schema = file_schema("image/png")
    schema["properties"]["file_base64"].pop("contentMediaType")
    schema["properties"]["content_type"]["enum"] = [
        "image/bmp",
        "image/png",
        "application/pdf",
    ]
    original = copy.deepcopy(schema)
    value = harness.input_sample({}, schema)
    assert value["content_type"] in original["properties"]["content_type"]["enum"]
    assert (
        base64.b64decode(value["file_base64"], validate=True)
        == (ROOT / FIXTURES[value["content_type"]]).read_bytes()
    )
    assert schema == original


def test_non_file_url_and_plain_text_content():
    value = harness.input_sample(
        {},
        {
            "type": "object",
            "required": ["content", "filename", "url"],
            "properties": {
                "content": {"type": "string"},
                "filename": {"type": "string"},
                "url": {"type": "string", "format": "uri"},
            },
        },
    )
    assert value["content"] == "Conformance.\n" and value["filename"].endswith(".txt")
    assert value["url"].startswith("https://")


def test_multipart_encoding_selects_real_bytes_without_rewriting_wire():
    doc = contract_for({}).doc
    body = doc["paths"]["/items"]["post"]["requestBody"]
    schema = {
        "type": "object",
        "required": ["file"],
        "properties": {"file": {"type": "string", "format": "binary"}},
    }
    body["content"] = {
        "multipart/form-data": {
            "schema": schema,
            "encoding": {"file": {"contentType": "image/png"}},
        }
    }
    original = copy.deepcopy(doc)
    contract = harness.Contract(doc)
    enriched = harness.enrich_config(
        contract,
        {"properties": {"file": {}}},
        {},
        [{"spec_operation": "POST /items"}],
    )
    assert enriched["file"] == (ROOT / "minimal.png").read_bytes()
    request = httpx.Request(
        "POST",
        "https://example.test/items",
        files={"file": ("minimal.png", enriched["file"], "image/png")},
    )
    request.read()
    contract.validate_request(request)
    # A bad top-level media type is still rejected by the real spec path.
    with pytest.raises(ValueError):
        contract.validate_request(
            httpx.Request(
                "POST",
                "https://example.test/items",
                content=enriched["file"],
                headers={"Content-Type": "image/png"},
            )
        )
    assert doc == original


async def test_ambiguous_file_is_reported_before_node_execution(monkeypatch):
    from nodes.core.registry import NODE_REGISTRY

    class Inputs(BaseModel):
        operation: Literal["upload"] = "upload"
        file_base64: str
        filename: str

    class Config(BaseModel):
        config: Inputs
        credentials: dict

    class Node:
        get_config_model = staticmethod(lambda: Config)

        def __init__(self, **kwargs):
            pytest.fail("Ambiguous file must not execute")

    monkeypatch.setitem(NODE_REGISTRY, "synthetic", Node)
    monkeypatch.setitem(harness.PROVIDERS, "synthetic", ("synthetic", {}))
    monkeypatch.setattr(harness, "spec_entry", lambda _: (None, {}))
    monkeypatch.setattr(harness, "load_specs", lambda _: [contract_for({}).doc])
    monkeypatch.setattr(harness, "INPUTS", {})
    report = await harness.run_provider("synthetic")
    assert report["fixture_errors"] == 1 and report["failed"] == 0
    assert (
        "Ambiguous or unsupported file type"
        in report["operations"][0]["fixture_errors"][0]
    )
    assert not report["operations"][0]["requests"]


async def test_binary_config_executes_as_bytes_and_report_is_serializable(monkeypatch):
    import json
    from nodes.core.registry import NODE_REGISTRY

    class Inputs(BaseModel):
        operation: Literal["upload"] = "upload"
        file: bytes = Field(json_schema_extra={"contentMediaType": "image/png"})
        filename: str
        content_type: Literal["image/png"]

        @field_validator("file")
        @classmethod
        def png(cls, value):
            assert value == (ROOT / "minimal.png").read_bytes()
            return value

    class Config(BaseModel):
        config: Inputs
        credentials: dict

    doc = contract_for({}).doc
    doc["paths"]["/items"]["post"]["requestBody"]["content"] = {
        "multipart/form-data": {
            "schema": {
                "type": "object",
                "required": ["file"],
                "properties": {"file": {"type": "string", "format": "binary"}},
            }
        },
    }

    class Node:
        scope_registry = None
        get_config_model = staticmethod(lambda: Config)

        def __init__(self, config, **kwargs):
            self.config = config.config

        async def execute(self, _):
            assert isinstance(self.config.file, bytes)
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://example.test/items",
                    files={
                        "file": (
                            self.config.filename,
                            self.config.file,
                            self.config.content_type,
                        )
                    },
                )
            return {"status": "success"}

    monkeypatch.setitem(NODE_REGISTRY, "synthetic", Node)
    monkeypatch.setitem(harness.PROVIDERS, "synthetic", ("synthetic", {}))
    monkeypatch.setattr(harness, "spec_entry", lambda _: (None, {}))
    monkeypatch.setattr(harness, "load_specs", lambda _: [doc])
    monkeypatch.setattr(harness, "INPUTS", {})
    report = await harness.run_provider("synthetic")
    assert report["passed"] == 1 and report["fixture_errors"] == report["failed"] == 0
    dumped = json.loads(json.dumps(report, default=harness.report_default))
    assert dumped["operations"][0]["config"]["file"] == {
        "encoding": "base64",
        "bytes": base64.b64encode((ROOT / "minimal.png").read_bytes()).decode("ascii"),
    }
    invalid = await harness.run_provider(
        "synthetic", config_overrides={"upload": {"file": b"bad"}}
    )
    assert invalid["fixture_errors"] == 1 and not invalid["operations"][0]["requests"]


def test_explicit_media_constraints_win_over_descriptive_examples():
    schema = {
        "type": "string",
        "format": "byte",
        "contentMediaType": "image/png",
        "description": "Use image/png, unlike application/pdf.",
    }
    assert (
        base64.b64decode(harness.input_sample({}, schema), validate=True)
        == (ROOT / "minimal.png").read_bytes()
    )
    with pytest.raises(FileFixtureError, match="Conflicting"):
        harness.input_sample({}, {**schema, "x-mime-type": "application/pdf"})
