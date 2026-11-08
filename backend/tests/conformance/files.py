"""Small checked-in file witnesses, selected only from schema evidence.

This module constructs inputs. It never changes a node, a validation schema,
provider examples, or captured traffic.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

from openapi_schema_validator import OAS31Validator, oas30_format_checker

ROOT = Path(__file__).with_name("fixtures")
FIXTURES = {
    "application/pdf": "minimal.pdf",
    "audio/wav": "minimal.wav",
    "audio/x-wav": "minimal.wav",
    "audio/mpeg": "minimal.mp3",
    "image/png": "minimal.png",
    "text/plain": "minimal.txt",
    # An explicit octet-stream declaration allows arbitrary bytes. Use the
    # real UTF-8 text fixture; do not infer a structured format from this MIME.
    "application/octet-stream": "minimal.txt",
}
EXTENSIONS = {
    "pdf": "application/pdf",
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "png": "image/png",
    "txt": "text/plain",
}
MIME_NAMES = {
    "mime",
    "mime_type",
    "mimetype",
    "content_type",
    "contenttype",
    "file_content_type",
}
NAME_NAMES = {"filename", "file_name"}


class FileFixtureError(ValueError):
    """File type/encoding is ambiguous, unsupported, or contradicts its schema."""


def metadata(schema):
    # Pydantic normally flattens json_schema_extra; also accept its literal form.
    return {**schema.get("json_schema_extra", {}), **schema}


def accepts(schema, value):
    return OAS31Validator(schema, format_checker=oas30_format_checker).is_valid(value)


def checked(schema, value, name):
    # binary is a wire byte sequence, not a JSON string. The real node and wire
    # validators still judge it; check its string constraints on the byte length.
    candidate = value.decode("latin1") if isinstance(value, bytes) else value
    if not accepts(schema, candidate):
        raise FileFixtureError(f"File fixture for {name!r} violates its schema")
    return value


def hints(schema):
    schema = metadata(schema)
    values = [
        schema[k]
        for k in (
            "const",
            "default",
            "contentMediaType",
            "x-mime-type",
            "accept",
            "ui:accept",
        )
        if isinstance(schema.get(k), str)
    ]
    values.extend(v for v in schema.get("enum", []) if isinstance(v, str))
    return values


def type_options(schema):
    """Use explicit type declarations ahead of examples or descriptive copy."""

    def parse(values):
        found = set()
        for value in values:
            for mime in re.findall(
                r"(?:application|audio|font|image|message|model|multipart|text|video)/[\w.+*-]+",
                value.lower(),
            ):
                matches = {
                    m
                    for m in FIXTURES
                    if m == mime or mime.endswith("/*") and m.startswith(mime[:-1])
                }
                found.update(matches or {mime})
            ext = value.lower().rsplit(".", 1)[-1]
            if ext in EXTENSIONS:
                found.add(EXTENSIONS[ext])
        return found

    declarations = [
        parse([schema[k]])
        for k in ("contentMediaType", "x-mime-type", "accept", "ui:accept")
        if isinstance(schema.get(k), str)
    ]
    if declarations:
        allowed = set.intersection(*declarations)
        if not allowed:
            raise FileFixtureError(
                "Conflicting or unsupported explicit file type declarations"
            )
        return allowed
    # An enum/const is normative; a default or explanatory example cannot add
    # another MIME/extension to its allowlist.
    constrained = parse(
        [
            v
            for v in [schema.get("const"), *schema.get("enum", [])]
            if isinstance(v, str)
        ]
    )
    if constrained:
        return constrained
    values = hints(schema)
    text = " ".join(str(schema.get(k, "")) for k in ("title", "description"))
    values.extend(
        re.findall(
            r"\b(?:application|audio|font|image|message|model|multipart|text|video)/[\w.+*-]+",
            text,
        )
    )
    values.extend("." + ext for ext in re.findall(r"\.([A-Za-z0-9]+)\b", text))
    return parse(values)


def is_file(name, schema, siblings=()):
    schema = metadata(schema)
    if (
        schema.get("format") in {"uri", "url"}
        or schema.get("ui:widget") == "media_upload"
    ):
        return False  # A hosted URL is not inline content.
    return (
        schema.get("format") in {"byte", "binary", "data-url"}
        or schema.get("contentEncoding") == "base64"
        or bool(
            schema.get("contentMediaType")
            and schema["contentMediaType"] != "application/json"
        )
        or name.endswith("_base64")
        or name in {"file", "content", "text", "body_file"}
        and bool(set(siblings) & (MIME_NAMES | NAME_NAMES) or type_options(schema))
    )


def file_values(properties, selected):
    """Coordinate content, filename and MIME siblings in a generation view.

    Multiple independent content fields need their own explicit type hints; a
    generic sibling is never silently assigned to two different files.
    """
    properties = {k: metadata(v) for k, v in properties.items()}
    fields = [
        k for k in selected if k in properties and is_file(k, properties[k], properties)
    ]
    result = {}
    for name in fields:
        schema = properties[name]
        stem = name.removesuffix("_base64")
        mime_keys = [
            k for k in properties if k in MIME_NAMES or k == stem + "_mime_type"
        ]
        name_keys = [
            k for k in properties if k in NAME_NAMES or k == stem + "_filename"
        ]
        # Literal UTF-8 content sometimes names its destination simply 'name'.
        if name == "text" and "name" in properties and type_options(schema):
            name_keys.append("name")
        if len(fields) > 1 and (mime_keys or name_keys):
            raise FileFixtureError(
                "Ambiguous file siblings for multiple content fields"
            )
        evidence = []
        for key in [name, *mime_keys, *name_keys]:
            options = type_options(properties[key])
            if options:
                evidence.append(options)
        if stem.lower() in EXTENSIONS:
            evidence.append({EXTENSIONS[stem.lower()]})
        # An unencoded JSON string of literal content is already text. This
        # does not infer the format of an encoded/binary upload without hints.
        if (
            not evidence
            and name in {"content", "text"}
            and not schema.get("contentEncoding")
            and schema.get("format") not in {"byte", "binary", "data-url"}
        ):
            evidence.append({"text/plain"})
        allowed = set.intersection(*evidence) if evidence else set()
        supported = [m for m in FIXTURES if m in allowed]
        if not supported:
            raise FileFixtureError(
                f"Ambiguous or unsupported file type for {name!r}: {sorted(allowed)}"
            )
        # Enum allowlists permit any member. Prefer a supported fixture, never
        # select a type outside the intersection of the supplied declarations.
        mime = supported[0]
        path = ROOT / FIXTURES[mime]
        data = path.read_bytes()
        for key in mime_keys:
            result[key] = checked(properties[key], mime, key)
        for key in name_keys:
            candidates = [
                v for v in hints(properties[key]) if v.lower().endswith(path.suffix)
            ] + [path.name]
            value = next((v for v in candidates if accepts(properties[key], v)), None)
            if value is None:
                raise FileFixtureError(f"No matching filename allowed for {key!r}")
            result[key] = value
        encoding = schema.get("contentEncoding")
        if encoding not in {None, "base64"}:
            raise FileFixtureError(
                f"Unsupported file encoding {encoding!r} for {name!r}"
            )
        data_url = (
            schema.get("format") == "data-url"
            or any(v.startswith("data:") for v in hints(schema))
            or str(schema.get("pattern", "")).startswith("^data:")
        )
        if data_url:
            value = f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
        elif (
            name.endswith("_base64")
            or schema.get("format") == "byte"
            or encoding == "base64"
        ):
            value = base64.b64encode(data).decode("ascii")
        elif schema.get("format") == "binary":
            value = data
        elif mime == "text/plain":
            value = data.decode("utf-8")
        else:
            raise FileFixtureError(
                f"Ambiguous file encoding for {name!r}; declare binary or base64"
            )
        result[name] = checked(schema, value, name)
    return result
