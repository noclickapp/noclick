"""Execute real nodes against immutable OpenAPI contracts, without sockets."""
from __future__ import annotations

import argparse
import ast
import base64
import copy
import dis
import fnmatch
import warnings
import asyncio
import hashlib
import json
import linecache
import os
import re
import socket
import struct
import time
import zlib
from contextlib import ExitStack, contextmanager
from functools import lru_cache
from dataclasses import asdict, dataclass, field
from email.parser import BytesParser
from pathlib import Path
from http.cookies import SimpleCookie
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qsl, unquote, urljoin, urlsplit

import httpx
import yaml
from openapi_core import Config, OpenAPI
from openapi_core.datatypes import RequestParameters
from openapi_core.templating.datatypes import TemplateResult
from openapi_core.templating.paths.datatypes import PathOperationServer
from openapi_core.templating.paths.finders import APICallPathFinder
from openapi_core.deserializing.styles import style_deserializers
from openapi_core.casting.schemas import (
    oas30_write_schema_casters_factory,
    oas31_schema_casters_factory,
)
from openapi_core.casting.schemas.casters import SchemaCaster
from openapi_core.casting.schemas.factories import SchemaCastersFactory
from openapi_core.deserializing.styles.deserializers import StyleDeserializer
from openapi_core.validation.schemas import (
    oas30_read_schema_validators_factory,
    oas31_schema_validators_factory,
)
from jsonschema_path import SchemaPath
from openapi_core.deserializing.styles.factories import StyleDeserializersFactory
from openapi_core.deserializing.media_types import media_type_deserializers
from openapi_core.deserializing.media_types.util import plain_loads
from openapi_core.deserializing.media_types.factories import (
    MediaTypeDeserializersFactory,
)
from openapi_core.deserializing.media_types.deserializers import MediaTypeDeserializer
from jsonschema.validators import extend
from openapi_schema_validator import oas30_format_checker
from werkzeug.datastructures import MultiDict
from werkzeug.http import parse_options_header

from tests.conformance.files import file_values, is_file
from tests.conformance.postman import PostmanContract, is_postman, validate_collection
from tests.conformance.transports import intercept_http
from tests.conformance import triggers
from tests.conformance.strings import (
    PatternError,
    config_shapes,
    python_pattern,
    string_sample,
    validation_patterns,
)

METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
TOKEN = "conformance-fake-token"
# Specs are never vendored here: CONFORMANCE_CATALOG names a folder whose manifest.json maps each provider
# to its node type, fake credential(s) and spec pins (file, sha256, version; or a `specs` list of them),
# beside optional inputs.json and witnesses.json. `server_url` binds relative servers to the documented host.
CATALOG = Path(os.environ["CONFORMANCE_CATALOG"]) if os.environ.get("CONFORMANCE_CATALOG") else None
PROVIDERS = {}
if CATALOG:
    for _name, _entry in json.loads((CATALOG / "manifest.json").read_text()).items():
        PROVIDERS[_name] = (_entry["node_type"], _entry.get("credential"))


def operation_credentials(entry, operations, default):
    """Select exact catalog mappings; never retry with a different credential."""
    credentials = entry.get("credentials", {})
    mapping = entry.get("operation_credentials", {})
    if not isinstance(credentials, dict) or any(
        not isinstance(name, str) or not name or not isinstance(value, dict)
        for name, value in credentials.items()
    ):
        raise ValueError("Catalog credentials must map names to credential objects")
    if not isinstance(mapping, dict):
        raise ValueError("Catalog operation_credentials must be an object")
    for operation, name in mapping.items():
        if operation not in operations:
            raise ValueError(f"Unknown catalog credential operation: {operation}")
        if not isinstance(name, str) or name not in credentials:
            raise ValueError(f"Unknown catalog credential for {operation}: {name}")

    def fake(value):
        if isinstance(value, dict):
            return {k: fake(v) for k, v in value.items()}
        if isinstance(value, list):
            return [fake(v) for v in value]
        return TOKEN if value == "<token>" else value

    selected = {}
    for operation in operations:
        credential = credentials[mapping[operation]] if operation in mapping else default
        if not isinstance(credential, dict):
            raise ValueError(f"No catalog credential configured for {operation}")
        selected[operation] = fake(credential)
    return selected


@contextmanager
def offline():
    """Fail closed for unhandled clients and accidental reference resolution."""

    def forbidden(*args, **kwargs):
        raise AssertionError("Network forbidden by conformance harness")

    with patch.object(socket.socket, "connect", forbidden), patch.object(
        socket.socket, "connect_ex", forbidden
    ), patch("socket.create_connection", forbidden), patch(
        "socket.getaddrinfo", forbidden
    ):
        yield


def resolve(doc, value):
    seen = set()
    while isinstance(value, dict) and isinstance(value.get("$ref"), str):
        ref = value["$ref"]
        if ref in seen or len(seen) > MAX_DEPTH:
            raise ValueError("Recursive reference requires a curated witness")
        seen.add(ref)
        if not ref.startswith("#/"):
            raise ValueError(f"External reference forbidden: {ref}")
        value = doc
        for part in ref[2:].split("/"):
            key = part.replace("~1", "/").replace("~0", "~")
            value = value[int(key)] if isinstance(value, list) else value[key]
    return value


# "full" fills optional properties and one array item too (to FULL_DEPTH), as real responses do: a spec that under-declares
# `required` otherwise feeds parsers responses no provider sends. Default stays minimal.
FULL = os.environ.get("CONFORMANCE_WITNESS") == "full"
# Realistic inputs per operation (operation -> {"config": a whole config, "source": the docs page its values come from}).
INPUTS = (
    json.loads((CATALOG / "inputs.json").read_text())
    if CATALOG and (CATALOG / "inputs.json").exists()
    else {}
)
# Provider-authored responses ("METHOD /path[?query]" -> {"body", "source", optional "headers"}):
# from its docs, checked against the spec before use.
WITNESSES = (
    json.loads((CATALOG / "witnesses.json").read_text())
    if CATALOG and (CATALOG / "witnesses.json").exists()
    else {}
)
# Provider-authored webhook deliveries for a contract that documents no `webhooks` or `callbacks` (event name ->
# {"body", "source", optional "headers", optional "webhook": the spec webhook whose schema it takes}).
EVENTS = (
    json.loads((CATALOG / "events.json").read_text())
    if CATALOG and (CATALOG / "events.json").exists()
    else {}
)
FULL_DEPTH = 6
MAX_DEPTH = 40


def input_cases(operation):
    """Each documented input is an independent run, including its fake identity.

    Additional cases name their node operation explicitly. Witness overrides
    reference entries in witnesses.json, so the existing source audit sees every
    body; they never splice or rewrite a provider's example to fit a request.
    """
    return [
        (name, entry)
        for name, entry in INPUTS.items()
        if entry.get("operation", name) == operation
    ] or [(operation, {})]


def scenario_witnesses(case):
    if "witnesses" not in case:
        return WITNESSES
    witnesses = {}
    for selector, reference in case.get("witnesses", {}).items():
        if reference not in WITNESSES:
            raise FixtureError(f"Unknown scenario witness: {reference}")
        witness = WITNESSES[reference]
        source = urlsplit(witness.get("source", ""))
        if source.scheme not in {"https", "http"} or not source.netloc:
            raise FixtureError(f"Scenario witness needs a documentation URL: {reference}")
        witnesses[selector] = witness
    return witnesses


def scenario_credential(credential, case):
    return {
        **credential,
        **{k: TOKEN if v == "<token>" else v for k, v in case.get("credential", {}).items()},
    }


def select_witness(request, key, witnesses):
    """An explicit query is an exact multimap match; a bare path is a fallback.

    An empty '?' explicitly selects requests with no query. Ordering and percent
    encoding do not matter, but duplicate values and blank values do. Ambiguous
    equivalent selectors are fixture errors, never dependent on catalog order.
    """
    actual = sorted(request.url.params.multi_items())
    matches = []
    for selector, witness in witnesses.items():
        path, query_marker, query = selector.partition("?")
        if path == key and query_marker and sorted(
            parse_qsl(query, keep_blank_values=True)
        ) == actual:
            matches.append((selector, witness))
    if len(matches) > 1:
        raise FixtureError(f"Ambiguous query witnesses for {key}: {[s for s, _ in matches]}")
    if matches:
        return matches[0]
    return (key, witnesses[key]) if key in witnesses else (None, None)


def sample(doc, schema, *, examples=True, depth=0, full=None, files=False):
    """Deterministic witness (minimal, or full with CONFORMANCE_WITNESS=full). Every response is independently validated.

    Unsupported constraints fail as fixture errors, never count as node bugs.
    No random state, clock, credentials, remote refs, or provider calls.
    """
    full = FULL if full is None else full
    schema = resolve(doc, schema)
    if depth > MAX_DEPTH:
        raise ValueError("Recursive schema requires a curated witness")
    if examples and "example" in schema:
        return schema["example"]
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    if "default" in schema and schema["default"] is not None:
        return schema["default"]
    if any(k in schema for k in ("allOf", "oneOf", "anyOf")):
        # Combine constraints BEFORE sampling: a required field in one branch
        # may have its concrete type/const/properties in another. Composition
        # does not increase the depth of the JSON value being constructed.
        value = sample(
            doc,
            input_shape(doc, schema),
            examples=examples,
            depth=depth,
            full=full,
            files=files,
        )
        discriminator = schema.get("discriminator", {})
        if discriminator and isinstance(value, dict):
            choices = schema.get("oneOf", schema.get("anyOf", []))
            choice = next(
                (c for c in choices if resolve(doc, c).get("type") == "object"),
                choices[0] if choices else {},
            )
            key = next(
                (
                    k for k, v in discriminator.get("mapping", {}).items()
                    if v == choice.get("$ref")
                ),
                None,
            )
            if key is not None:
                value[discriminator["propertyName"]] = key
        # An overlapping oneOf may reject the first branch's witness. Try the
        # remaining branches, but judge every candidate against the ENTIRE
        # union, never merely the branch used to construct it.
        if "oneOf" in schema and "openapi" in doc and not discriminator:
            root = SchemaPath.from_dict(
                validation_patterns({**doc, "x-conformance-witness": schema})
            )
            factory = (
                oas30_read_schema_validators_factory
                if doc["openapi"].startswith("3.0.")
                else oas31_schema_validators_factory
            )
            validator = factory.create(root, root / "x-conformance-witness")
            if not validator.validator.is_valid(value):
                for choice in schema["oneOf"][1:]:
                    try:
                        candidate = sample(
                            doc,
                            input_shape(doc, {**schema, "oneOf": [choice]}),
                            examples=examples,
                            depth=depth,
                            full=full,
                            files=files,
                        )
                    except ValueError:
                        continue
                    if validator.validator.is_valid(candidate):
                        return candidate
                # properties/required do not imply type: object in JSON
                # Schema. An untyped alternative may accept only non-objects
                # once overlapping object branches are excluded by oneOf.
                for candidate in (None, False, 1, "1", [], {}):
                    if validator.validator.is_valid(candidate):
                        return candidate
        return value
    typ = schema.get("type", "object" if "properties" in schema else "string")
    if isinstance(typ, list):
        typ = next((t for t in typ if t != "null"), "null")
    if typ == "object":
        properties = schema.get("properties", {})
        resolved = (
            {k: input_shape(doc, v) for k, v in properties.items()}
            if files
            else properties
        )
        selected = [
            k
            for k, sub in resolved.items()
            if (k in schema.get("required", []) or (full and depth < FULL_DEPTH))
            and not sub.get("writeOnly")
        ]
        if files and any(is_file(k, v, resolved) for k, v in resolved.items()):
            # Optional unset knobs need not accompany an inline file (notably
            # its alternative URL source). Keep explicit non-null defaults.
            selected = [
                k
                for k in selected
                if k in schema.get("required", [])
                or resolved[k].get("default", True) is not None
                or k.endswith("_base64")
            ]
        generated = file_values(resolved, selected) if files else {}
        value = {
            key: sample(
                doc,
                properties[key],
                examples=examples,
                depth=depth + 1,
                full=full,
                files=files,
            )
            for key in selected
            if key not in generated
        }
        value.update(generated)
        for key in schema.get("required", []):
            if key in schema.get("properties", {}):
                continue
            additional = schema.get("additionalProperties", True)
            if additional is False:
                raise ValueError(
                    f"Required property {key!r} is undeclared and additionalProperties is false"
                )
            # Required need not have a properties entry in JSON Schema. Use
            # its actual additional-properties constraint, or an unconstrained
            # null. This remains a synthetic witness, never an authored example.
            value[key] = (
                sample(
                    doc,
                    additional,
                    examples=examples,
                    depth=depth + 1,
                    full=full,
                    files=files,
                )
                if isinstance(additional, dict)
                else None
            )
        return value
    if typ == "array":
        return [
            sample(
                doc,
                schema.get("items", {}),
                examples=examples,
                depth=depth + 1,
                full=full,
                files=files,
            )
            for _ in range(
                max(schema.get("minItems", 0), 1 if full and depth < FULL_DEPTH else 0)
            )
        ]
    if typ in ("integer", "number"):
        return max(1, schema.get("minimum", 1))
    if typ == "boolean":
        return False
    if typ == "null":
        return None
    if files and is_file("", schema):
        return file_values({"content": schema}, ["content"])["content"]
    if schema.get("contentMediaType") == "application/json":
        value = sample(
            doc,
            schema.get("contentSchema", {"type": "object"}),
            examples=examples,
            depth=depth + 1,
            full=full,
            files=files,
        )
        return string_sample(schema, candidates=[json.dumps(value)])
    return string_sample(schema)


# Nodes that guard their requests (utils.ssrf) resolve the host first; offline() refuses DNS. Answer with a fixed
# public address instead: no socket opens either way, since every request is captured by the mock transport.
PUBLIC_ADDRESS = "93.184.215.14"


@contextmanager
def resolved_offline():
    try:
        import utils.ssrf as ssrf
    except ImportError:
        yield
        return

    async def resolve(host, *args, **kwargs):
        return [PUBLIC_ADDRESS]

    names = [n for n in ("_resolve_host_addresses", "resolve_host_addresses") if hasattr(ssrf, n)]
    with ExitStack() as stack:
        for name in names:
            stack.enter_context(patch.object(ssrf, name, resolve))
        yield


# A dotted host name with an optional port and base path, as some specs give a server (`api.air.inc`).
BARE_HOST = re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?::[0-9]+)?(?:/\S*)?")


def server_prefix(server, request):
    """The base path a request matches under one of the spec's servers, or None.

    A server URL may be a template (`https://{tenantDomain}/api/v2`, `https://api.bigcommerce.com/stores/{store_hash}/v3`):
    each variable matches one host label run or path segment, limited to its `enum` where the spec lists one.
    """
    url = server["url"]
    if BARE_HOST.fullmatch(url):
        # A bare host name names that host over HTTPS; OpenAPI would read it as a path relative to the document,
        # which no request to the provider could match.
        url = "https://" + url
    variables = server.get("variables", {})

    def pattern(text, segment):
        out, pos = "", 0
        for m in re.finditer(r"\{([^}]+)\}", text):
            out += re.escape(text[pos : m.start()])
            enum = (variables.get(m.group(1)) or {}).get("enum")
            out += (
                "(?:" + "|".join(re.escape(str(e)) for e in enum) + ")"
                if enum
                else segment
            )
            pos = m.end()
        return out + re.escape(text[pos:])

    # Parse before substituting: urlsplit cannot recognize a templated scheme.
    m = re.fullmatch(r"(?:(.*?)://([^/]*))?(.*)", url)
    scheme, authority, path = m.groups()
    if url.startswith("//"):
        authority, slash, tail = url[2:].partition("/")
        path = "/" + tail if slash else ""
    if scheme and not re.fullmatch(
        pattern(scheme, r"[a-z][a-z0-9+.-]*"), request.url.scheme
    ):
        return None
    if authority is not None:
        if authority.startswith("["):
            host_match = re.fullmatch(r"\[([^]]+)\](?::(.*))?", authority)
            if host_match is None:
                return None
            host, port = host_match.groups()
        else:
            host, sep, port = authority.rpartition(":")
            if not sep:
                host, port = authority, None
        if not re.fullmatch(pattern(host, r"[^/:]+"), request.url.host):
            return None
        actual_port = request.url.port or {"https": 443, "http": 80}.get(
            request.url.scheme
        )
        if port is not None:
            if not re.fullmatch(pattern(port, r"[0-9]+"), str(actual_port)):
                return None
        elif request.url.port is not None:
            return None
    found = re.match(pattern(path.rstrip("/"), r"[^/]+"), wire_path(request))
    if found and (
        len(found.group(0)) == len(wire_path(request))
        or wire_path(request)[len(found.group(0))] == "/"
    ):
        return found.group(0)
    return None


def wire_path(request):
    """Match URL segments before decoding; %2F is data inside a segment."""
    return request.url.raw_path.split(b"?", 1)[0].decode("ascii")


class ContractPathFinder(APICallPathFinder):
    @staticmethod
    def servers_iterator(name, operations_iter, spec, base_url=None):
        # openapi-core treats {protocol}:// as relative and insists on an
        # explicit :443. Use the same strict matcher as Contract.match while
        # keeping its path, parameter, body, security and response validators.
        for path, operation, path_result in operations_iter:
            servers = operation.get("servers") or path.get("servers") or spec["servers"]
            base = name.rsplit(path_result.resolved, 1)[0]
            request = httpx.Request("GET", base)
            for server in servers:
                prefix = server_prefix(server.read_value(), request)
                if prefix is not None and prefix == wire_path(request).rstrip("/"):
                    yield PathOperationServer(
                        path,
                        operation,
                        server,
                        path_result,
                        TemplateResult(server["url"], {}),
                    )


def spec_entry(provider):
    """A provider's pins come from the catalog alone."""
    if CATALOG is None:
        raise ValueError("No catalog: set CONFORMANCE_CATALOG to a catalog folder")
    manifest = json.loads((CATALOG / "manifest.json").read_text())
    if provider not in manifest:
        raise ValueError(f"{provider}: not in the catalog's manifest.json")
    return CATALOG, manifest[provider]


def json_suffix_media_types(doc):
    """Every application/*+json media type the spec names under a content map, as written."""
    found = set()

    def walk(value):
        if isinstance(value, dict):
            content = value.get("content")
            if isinstance(content, dict):
                for media in content:
                    base = str(media).split(";", 1)[0].strip().lower()
                    if base.startswith("application/") and base.endswith("+json"):
                        found.update({media, base})
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(doc)
    return sorted(found)


def load_spec(provider, entry=None):
    base, provider_entry = spec_entry(provider)
    entry = entry or provider_entry

    def pinned_path(filename):
        path = (base / filename).resolve()
        if Path(filename).is_absolute() or not path.is_relative_to(base.resolve()):
            raise ValueError("Spec path escapes catalog directory")
        return path

    raw = pinned_path(entry["file"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise ValueError(f"{provider}: spec hash differs from manifest")

    class SpecLoader(yaml.SafeLoader):
        pass

    # YAML 1.2 permits a plain '=' string (Algolia's official analytics spec).
    SpecLoader.add_constructor(
        "tag:yaml.org,2002:value", lambda loader, node: loader.construct_scalar(node)
    )
    # YAML 1.2 (and the JSON an OpenAPI document is) has no timestamp type: an unquoted
    # date example stays the string the spec wrote (Bookwhen's start_at), not a datetime.
    SpecLoader.add_constructor(
        "tag:yaml.org,2002:timestamp",
        lambda loader, node: loader.construct_scalar(node),
    )

    def parse_document(content, filename):
        return (
            json.loads(json.dumps(yaml.load(content, Loader=SpecLoader)))
            if filename.endswith((".yaml", ".yml"))
            else json.loads(content)
        )

    doc = parse_document(raw, entry["file"])
    if entry.get("format") == "postman":
        validate_collection(doc)
        source = urlsplit(entry.get("source_url", ""))
        if source.scheme not in {"http", "https"} or not source.netloc or source.fragment:
            raise ValueError("Catalog Postman source_url requires an absolute HTTP URL")
        if "version" not in entry or doc["info"].get("version") != entry["version"]:
            raise ValueError("Spec version differs from manifest")
        return doc
    if is_postman(doc):
        raise ValueError("Postman collections require format: postman")
    if doc["info"]["version"] != entry["version"]:
        raise ValueError("Spec version differs from manifest")

    includes = entry.get("includes", [])
    if not isinstance(includes, list):
        raise ValueError("Catalog includes must be a list")
    main_source = entry.get("source_url")
    if includes:
        source = urlsplit(main_source or "")
        if (
            source.scheme not in {"http", "https"}
            or not source.netloc
            or source.fragment
        ):
            raise ValueError("Catalog spec source_url requires an absolute HTTP URL")
    files = {}
    for include in includes:
        if (
            not isinstance(include, dict)
            or not {"file", "sha256", "source_url"} <= include.keys()
        ):
            raise ValueError(
                "Each catalog include requires file, sha256 and source_url"
            )
        source = urlsplit(include["source_url"])
        if (
            source.scheme not in {"http", "https"}
            or not source.netloc
            or source.fragment
        ):
            raise ValueError("Catalog include source_url requires an absolute HTTP URL")
        if include["source_url"] in files:
            raise ValueError("Duplicate catalog include source_url")
        content = pinned_path(include["file"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != include["sha256"]:
            raise ValueError(f"{provider}: include hash differs from manifest")
        if include["source_url"] == main_source and content != raw:
            raise ValueError("Include conflicts with main spec source_url")
        files[include["source_url"]] = (include["file"], content)

    # Resolve URI paths against their publishing URL, never against local filenames.
    # The manifest alone grants access to a hash-checked file inside the catalog.
    documents = {main_source: doc}
    bundled = []
    targets = {}
    active = set()
    bundle_key = "x-conformance-includes"
    if includes and bundle_key in doc:
        raise ValueError(f"Spec already defines {bundle_key}")

    def pointer(document, fragment):
        if not fragment:
            return document
        fragment = unquote(fragment)
        if not fragment.startswith("/"):
            raise ValueError("Reference fragment must be a JSON pointer")
        value = document
        for part in fragment[1:].split("/"):
            if re.search(r"~(?![01])", part):
                raise ValueError("Invalid JSON pointer escape")
            key = part.replace("~1", "/").replace("~0", "~")
            if isinstance(value, list):
                if not re.fullmatch(r"0|[1-9][0-9]*", key):
                    raise ValueError("Invalid JSON pointer array index")
                value = value[int(key)]
            else:
                value = value[key]
        return value

    def target(source, fragment, description):
        key = (source, fragment, description)
        if key in targets:
            index = targets[key]
            return (
                {"$ref": f"#/{bundle_key}/{index}"} if key in active else bundled[index]
            )
        filename, content = files[source]
        structured = filename.endswith((".yaml", ".yml", ".json"))
        if not structured and not (description and not fragment):
            raise ValueError("Text includes are only allowed for descriptions")
        if source not in documents:
            documents[source] = (
                parse_document(content, filename) if structured else content.decode("utf-8")
            )
        index = len(bundled)
        targets[key] = index
        bundled.append(None)
        active.add(key)
        bundled[index] = bundle(
            pointer(documents[source], fragment), source, description
        )
        active.remove(key)
        return bundled[index]

    def bundle(value, source, description=False):
        if isinstance(value, dict):
            ref = value.get("$ref")
            if isinstance(ref, str) and not (
                source == main_source and ref.startswith("#/")
            ):
                uri = urlsplit(ref)
                if (
                    uri.scheme
                    or uri.netloc
                    or ref.startswith(("/", "\\"))
                    or "\\" in ref
                    or uri.query
                    or (not uri.path and not ref.startswith("#/"))
                ):
                    raise ValueError("Remote references are forbidden")
                destination = urljoin(source or "", uri.path)
                if not includes or destination not in files:
                    raise ValueError(
                        f"Remote references are forbidden: unpinned relative reference or source_url mismatch: {ref}"
                    )
                resolved = target(destination, uri.fragment, description)
                if len(value) == 1:
                    return resolved
                # Keep reference siblings' dialect-specific semantics intact.
                index = targets[(destination, uri.fragment, description)]
                value = {**value, "$ref": f"#/{bundle_key}/{index}"}
            return {
                key: child
                if key == "$ref" and isinstance(child, str)
                else bundle(child, source, key == "description")
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [bundle(child, source) for child in value]
        return value

    doc = bundle(doc, main_source)
    if bundled:
        doc[bundle_key] = bundled
    return doc


def load_specs(provider):
    """Keep documents isolated: component names and security may differ."""
    _, entry = spec_entry(provider)
    if "specs" not in entry:
        return [load_spec(provider)]
    if not isinstance(entry["specs"], list) or not entry["specs"]:
        raise ValueError("Catalog specs must be a nonempty list")
    for spec in entry["specs"]:
        if (
            not isinstance(spec, dict)
            or not {"file", "sha256", "version", "source_url"} <= spec.keys()
        ):
            raise ValueError(
                "Each catalog spec requires file, sha256, version and source_url"
            )
        source = urlsplit(spec["source_url"])
        if source.scheme not in {"http", "https"} or not source.netloc:
            raise ValueError("Catalog spec source_url requires an absolute HTTP URL")
    return [load_spec(provider, spec) for spec in entry["specs"]]


def bind_server_origin(server, server_url):
    """The URL a server whose origin the spec leaves unknown takes from the catalog's documented `server_url`, or None.

    Two shapes leave it unknown. A relative server (`/v1`) resolves, as OpenAPI says, against a host: the documented
    API's origin, keeping its own path (so `server_url` https://api.example.test/v1 and `/v1` give that same URL).
    An origin placeholder before a base path that the spec never defines (`{{API_URL}}/v2/public/`, Postman's syntax,
    in VirtualBadge's spec; or `{base}/v1` with no default) stands for the whole documented `server_url`, its base path
    kept after it. A whole-URL `{variable}` keeps its own binding rules below."""
    url = server.get("url") if isinstance(server, dict) else None
    if not server_url or not isinstance(url, str):
        return None
    if url.startswith("/") and not url.startswith("//"):
        origin = urlsplit(server_url)
        return f"{origin.scheme}://{origin.netloc}" + url.rstrip("/")
    placeholder = re.fullmatch(r"\{\{([^{}]+)\}\}(/.*)?|\{([^{}]+)\}(/.*)", url)
    if placeholder:
        name = placeholder[1] or placeholder[3]
        path = placeholder[2] or placeholder[4] or ""
        if not (server.get("variables") or {}).get(name, {}).get("default"):
            return server_url.rstrip("/") + path.rstrip("/")
    return None


def cookie_values(request):
    cookie = SimpleCookie()
    cookie.load(request.headers.get("cookie", ""))
    return {key: value.value for key, value in cookie.items()}


def request_adapter(request):
    media, separator, parameters = request.headers.get("content-type", "").partition(";")
    return SimpleNamespace(
        host_url=f"{request.url.scheme}://{request.url.netloc.decode()}",
        path=wire_path(request),
        method=request.method.lower(),
        body=request.content or None,
        # MIME names are case-insensitive; multipart boundaries are not.
        content_type=media.lower() + separator + parameters,
        parameters=RequestParameters(
            query=MultiDict(request.url.params.multi_items()),
            header=request.headers,
            cookie=cookie_values(request),
            path={},
        ),
    )


def response_adapter(response):
    return SimpleNamespace(
        status_code=response.status_code,
        data=response.content,
        content_type=response.headers.get("content-type", ""),
        headers=response.headers,
    )


def reason(exc):
    """Keep nested validator errors: the top-level message often hides the field."""
    parts, seen = [], set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        parts.append(f"{type(exc).__name__}: {exc}")
        exc = exc.__cause__ or exc.__context__
    return " / ".join(parts)


@dataclass
class OperationResult:
    operation: str
    scenario: str | None = None
    requests: list = field(default_factory=list)
    failures: list = field(default_factory=list)
    fixture_errors: list = field(default_factory=list)
    skipped: str | None = None
    scope_checks: int = 0
    config: dict = field(default_factory=dict)
    # A webhook or poll trigger's own checks (triggers.py): its events, new-item detection and agent event.
    trigger: dict | None = None

    @property
    def passed(self):
        if self.trigger is not None and self.trigger.get("failures"):
            return False
        if self.trigger is not None and self.trigger.get("kind") == "webhook":
            # Judged by its deliveries; a registration it makes still meets the contract.
            return not (self.failures or self.fixture_errors or self.skipped)
        return bool(self.requests) and not (
            self.failures or self.fixture_errors or self.skipped
        )


ORDINARY_IDS = ("1", "a1b2c3", "65f8a2b4c9d7e1234567890b", "3fa85f64-5717-4562-b3fc-2c963f66afa6")


def drop_placeholder_patterns(doc):
    """A path parameter whose `pattern` accepts only its own placeholder (`^:webhookId$`, a Postman conversion
    artefact in Bouncie's spec) describes the template, not the value: no real id could ever be sent. Such a pattern
    is dropped; a pattern any ordinary id satisfies, or one the placeholder doesn't, is kept. Rewrites `doc`."""
    def quietly(value):
        try:
            return resolve(doc, value)
        except (IndexError, KeyError, TypeError, ValueError):
            return None  # a reference the harness can't follow is left as written

    for item in (doc.get("paths") or {}).values():
        item = quietly(item)
        if not isinstance(item, dict):
            continue
        operations = [op for op in (quietly(item[m]) for m in METHODS & item.keys()) if isinstance(op, dict)]
        for parameter in [*item.get("parameters", []), *(p for op in operations for p in op.get("parameters", []))]:
            parameter = quietly(parameter)
            if not isinstance(parameter, dict) or parameter.get("in") != "path":
                continue
            schema = quietly(parameter.get("schema"))
            if not isinstance(schema, dict) or not isinstance(schema.get("pattern"), str):
                continue
            try:
                pattern = re.compile(schema["pattern"])
            except re.error:
                continue
            name = parameter.get("name", "")
            if (any(pattern.search(p) for p in (f":{name}", "{" + name + "}"))
                    and not any(pattern.search(value) for value in ORDINARY_IDS)):
                del schema["pattern"]


def bracket_loads(explode, name, schema_type, location):
    """Stripe's published deepObject extension includes arrays and scalars.

    openapi-core only implements (explode=True, type=object), even for absent
    optional fields. Decode wire brackets here; its caster and validator still
    enforce the original schema. Never silently replace the request body.
    """
    if name in location:
        return location[name]
    pairs = [
        (key[len(name) :], value)
        for key, value in location.items()
        if key.startswith(name + "[")
    ]
    if not pairs:
        raise KeyError(name)
    tree = {}
    for suffix, value in pairs:
        parts = re.findall(r"\[([^\]]*)\]", suffix)
        cursor = tree
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value

    def lists(value):
        if not isinstance(value, dict):
            return value
        if value and all(k.isdigit() for k in value):
            return [lists(value[k]) for k in sorted(value, key=int)]
        return {k: lists(v) for k, v in value.items()}

    if schema_type == "array" and set(tree) == {""}:
        return location.getlist(name + "[]")
    return lists(tree)


EXPRESS_SEGMENT = re.compile(r"(?<=/):([A-Za-z_][A-Za-z0-9_]*)(?=/|$)")


def path_parameter_names(doc, item, operation):
    parameters = (resolve(doc, p) for p in [*item.get("parameters", []), *operation.get("parameters", [])])
    return {p.get("name") for p in parameters if isinstance(p, dict) and p.get("in") == "path"}


def express_path_templates(doc):
    """A `/:name` segment every operation of its path declares as a path parameter is that parameter's template, as
    Express-style exports write it (Eduzz: `/webhook/v1/subscription/:id`); OpenAPI reads it as literal text, so no
    request could match. A colon segment no operation declares stays literal. Rewrites `doc` in place."""
    paths = doc.get("paths") or {}
    renamed = {}
    for path, item in paths.items():
        names = EXPRESS_SEGMENT.findall(path)
        templated = EXPRESS_SEGMENT.sub(r"{\1}", path)
        if not names or templated in paths:
            continue
        try:
            item = resolve(doc, item)
            operations = [resolve(doc, item[m]) for m in METHODS & item.keys()]
            declared = all(set(names) <= path_parameter_names(doc, item, op) for op in operations)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            continue  # a reference the harness can't follow leaves the path as written
        if operations and declared:
            renamed[path] = templated
    if renamed:
        doc["paths"] = {renamed.get(path, path): item for path, item in paths.items()}


def template_pattern(path):
    """Escape literal URL characters; retain captures for actual path values."""
    parts, names = [], []
    for part in re.split(r"(\{[^}]+\})", path):
        if part.startswith("{") and part.endswith("}"):
            name = part[1:-1]
            names.append(name)
            parts.append(
                "(.*)" if name == "path" else "(.+)" if name == "ref" else "([^/]+)"
            )
        else:
            parts.append(re.escape(part))
    return re.compile("^" + "".join(parts) + "$"), names


def input_shape(doc, schema, *, depth=0):
    """Select an input branch while retaining constraints on its parent.

    In particular GitHub's reviewer anyOf contains only required lists; the
    property definitions live on the parent, not inside the chosen branch.
    This is witness construction only. Validation always uses the full schema.
    """
    if depth > MAX_DEPTH:
        raise ValueError("Recursive input schema requires a curated witness")
    schema = dict(resolve(doc, schema))
    parts = schema.pop("allOf", [])
    for union in ("oneOf", "anyOf"):
        choices = schema.pop(union, [])
        if choices:
            choice = next(
                (c for c in choices if resolve(doc, c).get("type") != "null"),
                choices[0],
            )
            if schema.get("discriminator"):
                choice = next(
                    (c for c in choices if resolve(doc, c).get("type") == "object"),
                    choice,
                )
            parts = [
                *parts,
                choice,
            ]
            discriminator = schema.get("discriminator", {})
            key = next(
                (
                    k for k, v in discriminator.get("mapping", {}).items()
                    if v == choice.get("$ref")
                ),
                None,
            )
            if key is not None:
                parts.append({
                    "properties": {discriminator["propertyName"]: {"const": key}}
                })
    for part in parts:
        part = input_shape(doc, part, depth=depth + 1)
        scalar_types = ("string", "number", "integer", "boolean")
        if (
            schema.get("type") == "object" and part.get("type") in scalar_types
        ) or (
            part.get("type") == "object" and schema.get("type") in scalar_types
        ):
            raise ValueError("Cannot merge scalar and object allOf witnesses")
        properties = dict(schema.get("properties", {}))
        for key, value in part.get("properties", {}).items():
            properties[key] = (
                {"allOf": [properties[key], value]} if key in properties else value
            )
        schema = {
            **schema,
            **part,
            **({"properties": properties} if properties else {}),
            "required": list(
                dict.fromkeys(
                    [
                        *schema.get("required", []),
                        *part.get("required", []),
                    ]
                )
            ),
        }
    return schema


def input_sample(doc, schema, selected=(), *, depth=0):
    if depth > MAX_DEPTH:
        raise ValueError("Recursive input schema requires a curated witness")
    schema = input_shape(doc, schema, depth=depth)
    typ = schema.get("type", "object" if "properties" in schema else "string")
    if isinstance(typ, list) and len([t for t in typ if t != "null"]) > 1:
        scalar_union_types(typ)
        for key in ("example", "default"):
            if schema.get(key) is not None:
                return schema[key]
        return sample(doc, schema, files=True)
    if typ == "object":
        properties = {
            k: input_shape(doc, v) for k, v in schema.get("properties", {}).items()
        }
        keys = [
            k
            for k, sub in properties.items()
            if k in set(schema.get("required", [])) | set(selected)
            and not sub.get("readOnly")
        ]
        generated = file_values(properties, keys)
        value = {
            key: input_sample(doc, properties[key], depth=depth + 1)
            for key in keys
            if key not in generated
        }
        value.update(generated)
        if not value:
            # Empty objects/array items vanish in bracket-encoded forms.
            # Choose an actual property rather than testing an absent value.
            key = next(
                (
                    k
                    for k, sub in schema.get("properties", {}).items()
                    if not resolve(doc, sub).get("readOnly")
                ),
                None,
            )
            if key is not None:
                value[key] = input_sample(
                    doc, schema["properties"][key], depth=depth + 1
                )
            elif schema.get("additionalProperties", True) is not False:
                additional = schema.get("additionalProperties", {})
                value["conformance"] = input_sample(
                    doc,
                    additional if isinstance(additional, dict) else {},
                    depth=depth + 1,
                )
        return value
    if typ == "array":
        return [
            input_sample(doc, schema.get("items", {}), depth=depth + 1)
            for _ in range(max(1, schema.get("minItems", 0)))
        ]
    # A Pydantic default may be an arbitrary placeholder. Provider constraints
    # (enum, format, pattern) determine the value of an input witness.
    return sample(
        doc,
        {k: v for k, v in schema.items() if k != "default"},
        examples=False,
        files=True,
    )


def enrich_config(contract, member, config, requests):
    """Supply provider inputs through the real config model, never the wire.

    Discover contracts from captured requests rather than copying node routing
    tables. Only same-named config properties and the documented extra_params
    escape hatch are writable. A missing or mis-serialized node field therefore
    remains a finding. Incompatible config types are kept, not coerced away.
    """
    properties = member.get("properties", {})
    result = dict(config)
    for record in requests:
        if "spec_operation" not in record:
            continue
        method, path = record["spec_operation"].split(" ", 1)
        operation = contract.doc["paths"][path][method.lower()]
        fields = {}
        required = set()
        for param in [
            *contract.doc["paths"][path].get("parameters", []),
            *operation.get("parameters", []),
        ]:
            param = resolve(contract.doc, param)
            if param["in"] == "query":
                fields[param["name"]] = {
                    **resolve(contract.doc, param.get("schema", {})),
                    **({"example": param["example"]} if "example" in param else {}),
                }
                if "examples" in param and "example" not in fields[param["name"]]:
                    for example in param["examples"].values():
                        example = resolve(contract.doc, example)
                        if "value" in example:
                            fields[param["name"]]["example"] = example["value"]
                            break
                if param.get("required"):
                    required.add(param["name"])
        body = resolve(contract.doc, operation.get("requestBody", {}))
        for media in body.get("content", {}).values():
            shape = input_shape(contract.doc, media.get("schema", {}))
            # Asana envelopes its request in data; this does not alter the
            # captured body or the schema used to validate it.
            if set(shape.get("properties", {})) == {"data"}:
                shape = input_shape(contract.doc, shape["properties"]["data"])
            body_fields = dict(shape.get("properties", {}))
            for key, encoding in media.get("encoding", {}).items():
                if key in body_fields and encoding.get("contentType"):
                    # Multipart's declared part MIME is generation evidence;
                    # the original encoding/schema still validates the wire.
                    body_fields[key] = {
                        **input_shape(contract.doc, body_fields[key]),
                        "contentMediaType": encoding["contentType"],
                    }
            fields.update(body_fields)
            required.update(shape.get("required", []))
            if body.get("required") and not required:
                # A required body with only optional fields still needs a
                # meaningful config field (e.g. editing a repository webhook).
                required.update(k for k in fields if k in properties)
            break
        # Some convenience configs expose a nested API field at the top level
        # (webhook config.url). Only lift unique leaf names present in the model;
        # ambiguity is left for a reviewed adapter, never guessed.
        leaves = {}

        def collect(sub, depth=0):
            if depth > MAX_DEPTH:
                raise ValueError("Recursive input schema requires a curated witness")
            sub = input_shape(contract.doc, sub, depth=depth)
            for name, child in sub.get("properties", {}).items():
                leaves.setdefault(name, []).append(child)
                collect(child, depth + 1)

        for sub in fields.values():
            collect(sub)
        for key, candidates in leaves.items():
            if key in config and key not in fields and len(candidates) == 1:
                fields[key] = candidates[0]
        generated = file_values(
            {k: input_shape(contract.doc, v) for k, v in fields.items()},
            [k for k in fields if k in required or k in config],
        )
        for key, sub in fields.items():
            if key not in required and key not in config and key not in generated:
                continue
            value = generated[key] if key in generated else input_sample(contract.doc, sub)
            if key in properties:
                # Check the actual Pydantic field later; don't turn an object
                # API field into a list to satisfy a broken node schema.
                result[key] = value
            elif "extra_params" in properties and key in required:
                result["extra_params"] = {**result.get("extra_params", {}), key: value}
    return result


def response_header(doc, header):
    """Construct bounded regex witnesses; the response validator remains final."""
    schema = resolve(doc, header.get("schema", {"type": "string"}))
    value = header["example"] if "example" in header else sample(doc, schema, full=False)
    if "pattern" in schema and not re.fullmatch(
        python_pattern(schema["pattern"]), str(value)
    ):
        # The same bounded string generator handles headers and JSON bodies.
        return string_sample(schema)
    return value


class FixtureError(ValueError):
    """A contract the offline validator cannot evaluate, not a node finding."""


def response_body(payload, media, schema, source, headers):
    """Serialize the witness as its actual media type, then validate the wire.

    Generated binary images are synthetic schema witnesses, never attributed
    to provider docs. Unknown structured encodings require a curated witness.
    """
    actual = headers.get("content-type", media)
    if "*" in actual:
        inferred = (
            "application/json"
            if isinstance(payload, (dict, list, int, float, bool)) or payload is None
            else "application/octet-stream"
            if isinstance(payload, bytes)
            else "text/plain"
        )
        if not fnmatch.fnmatchcase(inferred, media):
            raise ValueError(f"Cannot choose a concrete response type for {media}")
        actual = inferred
    wire_media = actual.split(";", 1)[0].strip().lower()
    result = {"headers": {**headers, "content-type": actual}}
    if wire_media == "application/json" or wire_media.endswith("+json"):
        # httpx treats json=None as no body, not the JSON null selected by a
        # nullable/untyped schema.
        return {**result, "content": b"null"} if payload is None else {**result, "json": payload}
    if source == "generated" and wire_media.startswith("image/"):
        if wire_media != "image/png" or (schema and schema.get("format") != "binary"):
            raise ValueError(
                f"Generated {wire_media} requires a curated binary witness"
            )

        def chunk(kind, data):
            return (
                struct.pack("!I", len(data))
                + kind
                + data
                + struct.pack("!I", zlib.crc32(kind + data))
            )

        payload = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack("!2I5B", 1, 1, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
            + chunk(b"IEND", b"")
        )
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    if not isinstance(payload, bytes):
        raise ValueError(f"Cannot serialize structured response as {wire_media}")
    return {**result, "content": payload}


def yaml_null_types(node):
    """`type: [object, null]` written in YAML parses as [\"object\", None]: YAML's null where OpenAPI 3.1 means the
    JSON type \"null\" (TCGdex's nullable object query parameters). Read it as \"null\". Rewrites in place."""
    stack = [node]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            types = value.get("type")
            if isinstance(types, list) and None in types:
                value["type"] = ["null" if t is None else t for t in types]
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)


def scalar_union_types(types):
    non_null = list(dict.fromkeys(t for t in types if t != "null"))
    if not non_null or not set(non_null) <= {"string", "integer", "number", "boolean"}:
        raise FixtureError(f"Ambiguous parameter serialization for types {types}")
    return non_null


def wire_type(schema):
    """Scalar alternatives share a style; validation keeps the entire schema."""
    typ = (schema / "type").read_str_or_list(None)
    if isinstance(typ, list):
        non_null = [t for t in typ if t != "null"]
        if len(non_null) == 1:
            return non_null[0]
        return scalar_union_types(typ)[0]
    if typ is None and any(key in schema for key in ("oneOf", "anyOf")):
        return parameter_union_types(schema)[0]
    return typ


def parameter_union_types(schema, depth=0):
    """Only scalar alternatives share an unambiguous OpenAPI style decoder."""
    if depth > MAX_DEPTH:
        raise FixtureError("Ambiguous parameter serialization for untyped union")
    typ = (schema / "type").read_str_or_list(None)
    if typ is not None:
        return scalar_union_types(typ if isinstance(typ, list) else [typ])
    types = []
    for keyword in ("oneOf", "anyOf"):
        if keyword in schema:
            for choice in schema / keyword:
                # A null alternative has no scalar wire representation.
                if (choice / "type").read_str_or_list(None) == "null":
                    continue
                try:
                    types.extend(parameter_union_types(choice, depth + 1))
                except FixtureError as exc:
                    raise FixtureError(
                        "Ambiguous parameter serialization for untyped union"
                    ) from exc
    if not types:
        raise FixtureError("Ambiguous parameter serialization for untyped union")
    return list(dict.fromkeys(types))


class ConcreteMediaTypeValidator:
    def _find_media_type(self, content, mimetype=None):
        media, parameters, definition = super()._find_media_type(content, mimetype)
        # A range selects the schema; the actual Content-Type selects its decoder.
        if "*" in media and mimetype:
            media = mimetype.split(";", 1)[0].strip().lower()
        return media, parameters, definition


class NullableSchemaCaster(SchemaCaster):
    def cast(self, value):
        types = (self.schema / "type").read_str_or_list(None)
        untyped = types is None and any(k in self.schema for k in ("oneOf", "anyOf"))
        if untyped:
            try:
                types = parameter_union_types(self.schema)
            except FixtureError:
                # Object body compositions still use openapi-core's caster.
                # Parameter styles reject these earlier, in wire_type().
                return super().cast(value)
        if isinstance(types, list):
            if value is None:
                return None
            non_null = [t for t in types if t != "null"]
            if len(non_null) == 1 and not untyped:
                return self.get_type_caster(wire_type(self.schema))(value)
            for typ in scalar_union_types(types):
                try:
                    candidate = self.get_type_caster(typ)(value)
                except (ValueError, TypeError, AttributeError):
                    continue
                if self.schema_validator.validator.is_valid(candidate):
                    return candidate
            raise ValueError(
                f"Value {value!r} is invalid for every scalar union member"
            )
        return super().cast(value)


class NullableSchemaCastersFactory(SchemaCastersFactory):
    def create(self, *args, **kwargs):
        caster = super().create(*args, **kwargs)
        return NullableSchemaCaster(
            caster.schema, caster.schema_validator, caster.types_caster
        )


class NullableStyleDeserializersFactory(StyleDeserializersFactory):
    def create(self, spec, schema, style, explode, name):
        decoder = self.style_deserializers.get(style)
        typ = (schema / "type").read_str_or_list(None)
        union = isinstance(typ, list) or (
            typ is None and any(k in schema for k in ("oneOf", "anyOf"))
        )
        if union and style in {"label", "matrix"}:
            original_decoder = decoder

            def decoder(explode, name, schema_type, location):
                # Our matched path adapter uses the OpenAPI parameter name;
                # openapi-core's RFC6570 decoders expect its style prefix too.
                key = (
                    ("." if style == "label" else ";") + name + ("*" if explode else "")
                )
                if key not in location and name in location:
                    location = {**location, key: location[name]}
                return original_decoder(explode, name, schema_type, location)

        return StyleDeserializer(
            style,
            explode,
            name,
            wire_type(schema) or "",
            self.schema_casters_factory.create(spec, schema),
            decoder,
        )


@dataclass(frozen=True)
class MultipartPart:
    data: bytes
    content_type: str | None


def multipart_loads(value, **parameters):
    """Parse bytes directly, preserving each part's media type and octets."""
    boundary = parameters.get("boundary", "")
    if not boundary or "\r" in boundary or "\n" in boundary:
        raise ValueError("Multipart body requires a boundary")
    message = BytesParser().parsebytes(
        f'Content-Type: multipart/form-data; boundary="{boundary}"\r\n\r\n'.encode()
        + value
    )
    if not message.is_multipart():
        raise ValueError("Invalid multipart body")
    parts = MultiDict()
    for part in message.get_payload():
        name = part.get_param("name", header="content-disposition")
        payload = part.get_payload(decode=True)
        if not isinstance(name, str) or not isinstance(payload, bytes):
            raise ValueError("Invalid multipart part")
        parts.add(name, MultipartPart(payload, part.get("Content-Type")))
    return parts


class WireMediaTypeDeserializer(MediaTypeDeserializer):
    def deserialize(self, value):
        if isinstance(value, MultipartPart):
            if self.schema is not None and self.schema.get("format") == "binary":
                return value.data
            if value.content_type:
                media, parameters = parse_options_header(value.content_type)
                decoder = self.evolve(self.schema, mimetype=media)
                decoder.parameters = parameters
                return decoder.deserialize(value.data)
            value = value.data
        return super().deserialize(value)

    def decode_property_style(self, prop_name, prop_schema, location, prop_encoding):
        if self.mimetype.startswith("multipart"):
            values = MultiDict()
            for name, part in location.items(multi=True):
                _, parameters = parse_options_header(part.content_type or "text/plain")
                values.add(
                    name,
                    part.data
                    if prop_schema.get("format") == "binary"
                    else plain_loads(part.data, **parameters),
                )
            location = values
        return super().decode_property_style(
            prop_name, prop_schema, location, prop_encoding
        )

    def decode_property_content_type(
        self, prop_name, prop_schema, location, prop_encoding=None
    ):
        if not self.mimetype.startswith("multipart"):
            return super().decode_property_content_type(
                prop_name, prop_schema, location, prop_encoding
            )
        if prop_name not in location:
            raise KeyError(prop_name)
        parts = location.getlist(prop_name)
        if prop_encoding is not None and "contentType" in prop_encoding:
            allowed = [
                parse_options_header(t.strip())[0]
                for t in prop_encoding["contentType"].split(",")
            ]
            for part in parts:
                actual = parse_options_header(
                    part.content_type or "application/octet-stream"
                )[0]
                if not any(fnmatch.fnmatchcase(actual, media) for media in allowed):
                    raise ValueError(
                        f"Multipart part {prop_name} Content-Type {actual} is not declared"
                    )
        if (prop_schema / "type").read_str_or_list(None) == "array":
            decoder = self.evolve(prop_schema / "items", mimetype="text/plain")
            return [decoder.deserialize(part) for part in parts]
        return super().decode_property_content_type(
            prop_name, prop_schema, location, prop_encoding
        )


class WireMediaTypeDeserializersFactory(MediaTypeDeserializersFactory):
    def create(self, *args, **kwargs):
        decoder = super().create(*args, **kwargs)
        return WireMediaTypeDeserializer(
            decoder.spec,
            decoder.style_deserializers_factory,
            decoder.media_types_deserializer,
            decoder.mimetype,
            schema=decoder.schema,
            schema_validator=decoder.schema_validator,
            schema_caster=decoder.schema_caster,
            encoding=decoder.encoding,
            **decoder.parameters,
        )


class BinarySchemaValidatorsFactory:
    """Use openapi-core's OAS 3.0 bytes convention for binary schemas in 3.1 too."""

    def __init__(self, factory):
        self.factory = factory

    @staticmethod
    @lru_cache
    def validator_class(base):
        def binary_type(validator, types, value, schema):
            if isinstance(value, bytes) and schema.get("format") == "binary":
                if types == "string" or isinstance(types, list) and "string" in types:
                    return
            yield from base.VALIDATORS["type"](validator, types, value, schema)

        def string_constraint(keyword):
            def validate(validator, constraint, value, schema):
                if isinstance(value, bytes) and schema.get("format") == "binary":
                    value = value.decode("latin-1")
                yield from base.VALIDATORS[keyword](
                    validator, constraint, value, schema
                )

            return validate

        return extend(
            base,
            {
                "type": binary_type,
                **{
                    k: string_constraint(k)
                    for k in ("minLength", "maxLength", "pattern")
                },
            },
        )

    def create(self, *args, **kwargs):
        schema_validator = self.factory.create(*args, **kwargs)
        validator = schema_validator.validator
        schema_validator.validator = self.validator_class(type(validator))(
            validator.schema,
            _resolver=validator._resolver,
            format_checker=validator.format_checker,
        )
        return schema_validator


def unsupported_dialect(doc):
    if doc.get("swagger") == "2.0":
        for path, item in doc.get("paths", {}).items():
            item = resolve(doc, item)
            for method in sorted(METHODS & item.keys()):
                operation = item[method]
                params = {}
                for param in [
                    *item.get("parameters", []), *operation.get("parameters", [])
                ]:
                    param = resolve(doc, param)
                    params[param["in"], param["name"]] = param
                bodies = [name for location, name in params if location == "body"]
                if len(bodies) > 1:
                    raise FixtureError(
                        f"Swagger 2.0 {method.upper()} {path} "
                        f"({operation.get('operationId', 'unnamed')}) declares multiple "
                        f"body parameters: {', '.join(bodies)}. Swagger permits only "
                        "one whole request body; merging these schemas or choosing "
                        "one would invent body semantics. Lossless conversion is "
                        "undefined; a corrected provider contract is required."
                    )
        raise FixtureError(
            "Swagger 2.0 is unsupported by openapi-core; a lossless OpenAPI 3 "
            "conversion is required before validation"
        )
    if not str(doc.get("openapi", "")).startswith(("3.0.", "3.1.", "3.2.")):
        raise FixtureError("Unsupported or missing OpenAPI dialect")


class Contract:
    def __init__(
        self, doc, *, auth_override=None, server_url=None, server_variables=None
    ):
        unsupported_dialect(doc)
        # OAS empty servers means relative URLs. A catalog can bind these to the
        # documented provider host without modifying the pinned document.
        doc = copy.deepcopy(doc)
        express_path_templates(doc)
        if server_url:
            base = urlsplit(server_url)
            if (
                base.scheme not in {"http", "https"}
                or not base.netloc
                or base.query
                or base.fragment
            ):
                raise ValueError("Catalog server_url requires an absolute HTTP URL")
        for obj in [
            doc,
            *[item for item in doc["paths"].values() if isinstance(item, dict)],
            *[
                op
                for item in doc["paths"].values()
                if isinstance(item, dict)
                for method, op in item.items()
                if method in METHODS
            ],
        ]:
            if "servers" in obj and not obj["servers"]:
                obj["servers"] = [{"url": server_url or "/"}]
            for server in obj.get("servers", []):
                bound = bind_server_origin(server, server_url)
                if bound:
                    server["url"] = bound
                    continue
                variable = re.fullmatch(r"\{([^}]+)\}", server["url"])
                if variable:
                    name = variable[1]
                    definition = server.get("variables", {}).get(name, {})
                    value = definition.get("default")
                    if value == "":
                        # A whole-URL variable with an empty default has no
                        # usable origin. Bind only to a documented catalog URL,
                        # never the host of the request being checked.
                        key = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
                        value = server_url or (server_variables or {}).get(key)
                    if value:
                        base = urlsplit(value)
                        if (
                            base.scheme not in {"http", "https"}
                            or not base.netloc
                            or base.query
                            or base.fragment
                            or (
                                definition.get("enum")
                                and value not in definition["enum"]
                            )
                        ):
                            raise ValueError(
                                "Whole server variable requires an allowed absolute HTTP URL"
                            )
                        server["url"] = value
        if not doc.get("servers"):
            doc["servers"] = [{"url": server_url or "/"}]
        drop_placeholder_patterns(doc)
        # RFC 7235 auth schemes are case-insensitive. HttpProvider lowercases
        # the header scheme but compares it with the spec's spelling verbatim.
        for scheme in doc.get("components", {}).get("securitySchemes", {}).values():
            scheme = resolve(doc, scheme)
            if scheme.get("type") == "http":
                scheme["scheme"] = scheme["scheme"].lower()
        yaml_null_types(doc)
        self.doc = doc
        self.auth_override = auth_override
        if auth_override is not None:
            # Either one of the HTTP schemes, or where the provider documents the credential goes: a header, query
            # parameter or cookie, optionally after a literal prefix (Zoho's "Zoho-oauthtoken ", Wix's bare key).
            placement = (
                isinstance(auth_override, dict)
                and "scheme" not in auth_override
                and auth_override.get("in") in {"header", "query", "cookie"}
                and isinstance(auth_override.get("name"), str)
                and auth_override["name"].strip()
                and isinstance(auth_override.get("prefix", ""), str)
            )
            if (
                not isinstance(auth_override, dict)
                or not (
                    placement
                    or str(auth_override.get("scheme", "")).lower()
                    in {"basic", "bearer", "token"}
                )
                or urlsplit(auth_override.get("source", "")).scheme
                not in {"http", "https"}
                or not urlsplit(auth_override["source"]).netloc
            ):
                raise ValueError(
                    "Auth override requires an HTTP scheme or a documented credential placement, and a documentation URL"
                )
        # jsonschema silently accepts every value for an uninstalled optional
        # format validator. A minimal CI install must enforce the same boundary
        # as a developer environment; never synthesize around missing checks.
        required_formats = {"uri", "date-time", "uri-template"}
        missing = required_formats - oas30_format_checker.checkers.keys()
        if missing:
            raise ValueError(
                f"Missing conformance format validators: {sorted(missing)}"
            )
        styles = dict(style_deserializers)
        styles["deepObject"] = bracket_loads
        nullable_types = doc["openapi"].startswith("3.1.")
        base_casters = oas31_schema_casters_factory if nullable_types else oas30_write_schema_casters_factory
        casters = NullableSchemaCastersFactory(
            base_casters.schema_validators_factory, base_casters.types_caster,
        )
        style_factory = NullableStyleDeserializersFactory(casters, styles)
        media_decoders = copy.copy(media_type_deserializers)
        media_decoders["text/csv"] = plain_loads
        media_decoders["multipart/form-data"] = multipart_loads
        # RFC 6839: a +json suffix (application/scim+json, application/vnd.x.v2+json, application/hal+json) is
        # JSON on the wire; openapi-core only knows application/json and would validate the raw bytes.
        for media in json_suffix_media_types(doc):
            media_decoders.setdefault(media, media_type_deserializers["application/json"])
        try:
            validator_doc = validation_patterns(doc)
        except PatternError as exc:
            raise FixtureError(str(exc)) from exc
        self.api = OpenAPI.from_dict(
            validator_doc,
            config=Config(
                spec_validator_cls=None,
                schema_casters_factory=casters if nullable_types else None,
                schema_validators_factory=(
                    BinarySchemaValidatorsFactory(oas31_schema_validators_factory)
                    if nullable_types else None
                ),
                path_finder_cls=ContractPathFinder,
                style_deserializers_factory=style_factory,
                media_type_deserializers_factory=WireMediaTypeDeserializersFactory(
                    style_factory,
                    media_decoders,
                ),
            ),
        )

        class WireRequestValidator(ConcreteMediaTypeValidator, self.api.request_validator_cls):
            def _get_simple_param_or_header(self, param_or_header, location, name=None):
                # Absence is not a transmitted default (which may even be null).
                self._deserialise_style(param_or_header, location, name=name)
                return super()._get_simple_param_or_header(
                    param_or_header, location, name=name
                )

            def _get_security(self, parameters, operation):
                # Only the explicit catalog override replaces the spec's security.
                if auth_override is not None:
                    return {}
                return super()._get_security(parameters, operation)

        self.api.request_validator_cls = WireRequestValidator

        class ConcreteResponseValidator(ConcreteMediaTypeValidator, self.api.response_validator_cls):
            pass

        self.api.response_validator_cls = ConcreteResponseValidator
        self.paths = []
        for path, item in doc["paths"].items():
            item = resolve(doc, item)
            for method in METHODS & item.keys():
                # Literal paths precede parameter paths, as OpenAPI specifies.
                self.paths.append(
                    (
                        path,
                        method,
                        template_pattern(path)[0],
                        (
                            {"servers": item["servers"], **item[method]}
                            if "servers" in item
                            else item[method]
                        ),
                    )
                )
        self.paths.sort(
            key=lambda x: (
                x[0].count("{"),
                -len(re.sub(r"\{[^}]+\}", "", x[0])),
                x[0],
                x[1],
            )
        )

    def match(self, request):
        for path, method, regex, op in self.paths:
            for server in op.get("servers", self.doc.get("servers", [{"url": "/"}])):
                prefix = server_prefix(server, request)
                if prefix is None:
                    continue
                actual = wire_path(request)
                if prefix and not actual.startswith(prefix + "/"):
                    continue
                if method == request.method.lower() and regex.fullmatch(
                    actual[len(prefix) :]
                ):
                    return path, method, op
        raise ValueError(f"No spec operation for {request.method} {request.url}")

    def adapter(self, request):
        """Pass the chosen template and actual path values to openapi-core.

        Its default path finder cannot match slash-containing GitHub ref/path
        values reliably. Matching stays method+host+base path+template; the
        original values are still validated against the provider's schemas.
        """
        path, _, op = self.match(request)
        adapter = request_adapter(request)
        pattern, names = template_pattern(path)
        for server in op.get("servers", self.doc.get("servers", [{"url": "/"}])):
            prefix = server_prefix(server, request)
            if prefix is None:
                continue
            match = pattern.fullmatch(wire_path(request)[len(prefix) :])
            if match:
                adapter.path_pattern = prefix + path
                adapter.parameters.path = dict(zip(names, map(unquote, match.groups())))
                return adapter
        raise ValueError("Cannot recover matched path parameters")

    def request_errors(self, request, operation):
        """OpenAPI-core does not implement OAuth2 verification/placement.

        Check placement for every security alternative explicitly; never verify
        fake tokens or call the authorization server. Then use its real schema,
        serialization, content type and parameter validators unchanged.
        """
        security = operation.get("security", self.doc.get("security", []))
        schemes = self.doc.get("components", {}).get("securitySchemes", {})
        if self.auth_override is not None:
            security = [{"override": []}]
            schemes = {
                "override": {"type": "http", "scheme": self.auth_override["scheme"]}
                if "scheme" in self.auth_override
                else {
                    "type": "apiKey",
                    "in": self.auth_override["in"],
                    "name": self.auth_override["name"],
                    "_override_prefix": self.auth_override.get("prefix", ""),
                }
            }

        def present(name):
            scheme = resolve(self.doc, schemes[name])
            kind = scheme["type"]
            if kind == "apiKey":
                locations = {
                    "header": request.headers,
                    "query": request.url.params,
                    "cookie": cookie_values(request),
                }
                value = locations[scheme["in"]].get(scheme["name"]) or ""
                prefix = scheme.get("_override_prefix", "")
                return value[: len(prefix)].lower() == prefix.lower() and bool(value[len(prefix) :].strip())
            auth = request.headers.get("authorization", "").split(" ", 1)
            if len(auth) != 2 or not auth[1].strip():
                return False
            if kind in ("oauth2", "openIdConnect") or (
                kind == "http" and scheme["scheme"].lower() == "bearer"
            ):
                return auth[0].lower() == "bearer"
            if kind == "http" and scheme["scheme"].lower() == "basic":
                try:
                    return (
                        auth[0].lower() == "basic"
                        and ":" in base64.b64decode(auth[1], validate=True).decode()
                    )
                except (ValueError, UnicodeError):
                    return False
            if self.auth_override is not None and kind == "http":
                return auth[0].lower() == scheme["scheme"].lower()
            raise ValueError(f"Unsupported security scheme: {scheme}")

        if security and not any(
            all(present(name) for name in alternative) for alternative in security
        ):
            yield ValueError(
                "Authentication is missing or in the wrong location/scheme"
            )
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message="Unsupported scheme type", category=UserWarning
            )
            try:
                yield from self.api.request_validator.iter_errors(self.adapter(request))
            except RecursionError as exc:
                raise FixtureError(
                    "Recursive request schema cannot be validated offline"
                ) from exc

    def validate_request(self, request):
        operation = self.match(request)[2]
        errors = list(self.request_errors(request, operation))
        if errors:
            raise ValueError(" / ".join(map(reason, errors)))

    def response(
        self, request, operation, key=None, record=None, witnesses=None,
        strict_witnesses=False,
    ):
        witness_key, witness = (
            select_witness(request, key, WITNESSES if witnesses is None else witnesses)
            if FULL else (None, None)
        )
        if strict_witnesses and witness is None:
            raise FixtureError(f"Scenario has no witness for {request.method} {request.url}")
        responses = operation["responses"]
        code = next(
            (c for c in sorted(responses) if c.startswith("2") and c.isdigit()), None
        )
        if code is None:
            # A range ("2XX") stands for any success code: answer 200.
            code = next((c for c in sorted(responses) if c.upper() == "2XX"), None)
        if code is None:
            code = "default" if "default" in responses else None
        if code is None:
            code = next(
                (c for c in sorted(responses) if c.startswith("3") and c.isdigit()),
                None,
            )
        if code is None:
            raise ValueError("No concrete success response in spec")
        definition = resolve(self.doc, responses[code])
        status = 200 if code.upper() in {"2XX", "DEFAULT"} else int(code)
        if code == "default" and witness is not None:
            status = witness.get("status", status)
            if not isinstance(status, int) or not 200 <= status < 300:
                raise ValueError("Default success witness requires a 2XX status")
        headers = httpx.Headers(witness.get("headers", {}) if witness else {})
        for name, header in (definition.get("headers") or {}).items() if FULL else ():
            header = resolve(self.doc, header)
            if header.get("required") and name.lower() != "content-type":
                value = headers.get(name)
                if value is None:
                    value = response_header(self.doc, header)
                headers[name] = value if isinstance(value, str) else json.dumps(value)
        content = definition.get("content", {})
        if not content:
            # A documented empty response (no content, or `content: {}`) has no body to validate; headers still do.
            # A spec that leaves out a body the provider documents (Katana's POST /webhooks returns the webhook's id
            # and token) gets the documented witness, unchanged: its own fields are then the response's schema. A
            # status that never carries a body (204, 205, 304) stays empty.
            documented = witness is not None and "body" in witness and status not in (204, 205, 304)
            response = httpx.Response(
                status,
                **(response_body(witness["body"], "application/json", {}, "docs", headers) if documented
                   else {"headers": headers}),
                request=request,
            )
            try:
                self.api.validate_response(
                    self.adapter(request), response_adapter(response)
                )
            except Exception as exc:
                if type(exc).__name__ != "MissingData" and "MissingData" not in reason(
                    exc
                ):
                    raise
            if documented:
                response.extensions["conformance_schema"] = ({}, triggers.example_schema(witness["body"]))
                if record is not None:
                    record["response_source"] = "docs"
                    record["response_witness"] = witness_key
                    record["response_source_url"] = witness.get("source")
            return response
        media_types = sorted(
            content, key=lambda m: not (m == "application/json" or m.endswith("+json"))
        )
        if "content-type" in headers:
            actual_media = headers["content-type"].split(";", 1)[0].strip().lower()
            media = next((m for m in content if m == actual_media), None) or next(
                (m for m in content if fnmatch.fnmatchcase(actual_media, m)), None
            )
            if media is None:
                raise ValueError(
                    "Documented response Content-Type is not declared in spec"
                )
            media_types = [media]
        # Provider-authored bodies first (a parser failing on these is a real defect), generated ones last.
        bodies = []
        if witness is not None:
            bodies.extend(("docs", witness["body"], m) for m in media_types)
        for media in media_types if FULL else ():
            if "example" in content[media]:
                bodies.append(("spec_example", content[media]["example"], media))
            for example in (content[media].get("examples") or {}).values():
                example = resolve(self.doc, example)
                if "value" in example:
                    bodies.append(("spec_example", example["value"], media))
        # Generated last: full (if on) then minimal, each with the spec's schema examples, then without.
        bodies += [
            ("generated", (f, ex), media)
            for f in ([True, False] if FULL else [False])
            for ex in (True, False)
            for media in media_types
        ]
        errors, docs_errors = [], []
        strict = strict_witnesses or bool(witness_key and "?" in witness_key)
        for source, body, media in bodies:
            # A selected documented witness must validate as one of the declared
            # media types; it never falls back to another example or a generated body.
            if source != "docs" and docs_errors and strict:
                raise FixtureError(f"Invalid documented witness {witness_key}: {docs_errors[0]}")
            try:
                schema = content[media].get("schema", {})
                payload = (
                    body
                    if source != "generated"
                    else sample(self.doc, schema, examples=body[1], full=body[0])
                )
                response = httpx.Response(
                    status,
                    **response_body(
                        payload, media, resolve(self.doc, schema), source, headers
                    ),
                    request=request,
                )
                self.api.validate_response(
                    self.adapter(request), response_adapter(response)
                )
                # The trigger checks read the node's field accesses against this schema.
                response.extensions["conformance_schema"] = (self.doc, schema)
                if record is not None and FULL:
                    record["response_source"] = source
                    if source == "docs":
                        record["response_witness"] = witness_key
                        record["response_source_url"] = witness.get("source")
                return response
            except Exception as exc:
                if source == "docs":
                    docs_errors.append(reason(exc))
                errors.append(reason(exc))
        raise ValueError("Cannot generate spec-valid response: " + errors[0])

    def scopes(self, node_cls, operation_name, operation, result):
        security = operation.get("security", self.doc.get("security", []))
        alternatives = []
        for alternative in security:
            scopes = set()
            for scheme, required in alternative.items():
                definition = (
                    self.doc.get("components", {})
                    .get("securitySchemes", {})
                    .get(scheme, {})
                )
                if definition.get("type") in ("oauth2", "openIdConnect"):
                    scopes.update(required)
            alternatives.append(scopes)
        if not alternatives or any(not s for s in alternatives):
            return
        result.scope_checks += 1
        registry = node_cls.scope_registry
        requirement = registry.get(operation_name) if registry else None
        declared = set(requirement.scopes) if requirement else set()
        if not any(scopes <= declared for scopes in alternatives):
            result.failures.append(
                f"scopes: spec alternatives {list(map(sorted, alternatives))}; registry {sorted(declared)}"
            )


@lru_cache(maxsize=128)
def source_tree(filename):
    return ast.parse("".join(linecache.getlines(filename)))


def provider_rejection(exc, response):
    """Accept an HTTP rejection, not an arbitrary parser crash on an error body.

    For manual provider exceptions, require an explicit raise in a status guard
    on this exact response. No exception-name allowlist can distinguish a node's
    deliberate ValueError from JSON/shape failures with the same exception type.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response is response
    tb = exc.__traceback__
    while tb and tb.tb_next:
        tb = tb.tb_next
    if tb is None or dis.opname[tb.tb_frame.f_code.co_code[tb.tb_lasti]] != "RAISE_VARARGS":
        return False
    try:
        tree = source_tree(tb.tb_frame.f_code.co_filename)
    except (OSError, SyntaxError):
        return False
    for guard in ast.walk(tree):
        if not isinstance(guard, ast.If):
            continue
        status_check = any(
            isinstance(part, ast.Attribute)
            and part.attr in {"status_code", "is_success", "is_error"}
            and isinstance(part.value, ast.Name)
            and tb.tb_frame.f_locals.get(part.value.id) is response
            for part in ast.walk(guard.test)
        )
        if status_check and any(
            isinstance(part, ast.Raise)
            and part.lineno <= tb.tb_lineno <= part.end_lineno
            for statement in guard.body + guard.orelse
            for part in ast.walk(statement)
        ):
            return True
    return False


async def run_provider(provider, *, config_overrides=None, enrich=True):
    from nodes.core.registry import NODE_REGISTRY

    node_type, default_credential = PROVIDERS[provider]
    node_cls = NODE_REGISTRY[node_type]
    model = node_cls.get_config_model()
    schema = model.model_json_schema()
    config_schema = schema["properties"]["config"]
    members = config_schema.get("oneOf", config_schema.get("anyOf", [config_schema]))
    entry = spec_entry(provider)[1]
    by_operation = {
        resolve(schema, m)["properties"]["operation"].get("const")
        or resolve(schema, m)["properties"]["operation"].get("enum", [None])[0]: resolve(schema, m)
        for m in members
    }
    credentials = operation_credentials(entry, by_operation, default_credential)
    contracts, contract_errors = [], []
    pins = entry.get("specs", [entry])
    for index, doc in enumerate(load_specs(provider)):
        try:
            binding_options = (
                {"host_bindings": pins[index].get("host_bindings")}
                if is_postman(doc) and index < len(pins) else {}
            )
            contracts.append(
                (PostmanContract if is_postman(doc) else Contract)(
                    doc,
                    auth_override=entry.get("auth_override"),
                    server_url=entry.get("server_url"),
                    # Whole-URL server variables bind only to the catalog's default credential.
                    server_variables=default_credential or {},
                    **binding_options,
                )
            )
        except FixtureError as exc:
            contract_errors.append(reason(exc))
    if provider == "stripe" and not contract_errors:
        # Probe the pinned version, never an unspecified account default.
        credentials = {
            op: {**credential, "stripe_version": contracts[0].doc["info"]["version"]}
            for op, credential in credentials.items()
        }
    trigger_events = triggers.contract_events(
        [c for c in contracts if not isinstance(c, PostmanContract)], EVENTS
    )
    try:
        signing, signing_error = triggers.signing_of(entry, contracts), None
    except FixtureError as exc:
        signing, signing_error = None, reason(exc)
    node_files = triggers.node_files(node_cls)
    results, covered = [], set()
    cases = [
        (op, member, name, entry)
        for op, member in by_operation.items()
        for name, entry in input_cases(op)
    ]
    # Replay whole operations for every saved Postman response, preserving every
    # request, node guard and readback. Plans select one response at a captured
    # request ordinal; no response is synthesized or rebound to input IDs.
    cases = [(op, member, name, case, {}) for op, member, name, case in cases]
    replayed = set()
    for op, member, case_name, case, response_plan in cases:
        result = OperationResult(op, scenario=case_name if case else None)
        if response_plan:
            result.scenario = f"{case_name}:postman:{sorted(response_plan.items())}"
        results.append(result)
        kind = (
            triggers.trigger_kind(node_cls, model, op)
            if member.get("x-is-trigger") is True or op.startswith("on_")
            else None
        )
        # A webhook trigger is fed the contract's events and a poll trigger checked on its list call (triggers.py);
        # any other trigger family (app-event subscriptions) is a passthrough on a manual run, not an API call.
        if kind:
            # Reported as a trigger even when it never gets as far as its own checks (an invalid config witness).
            result.trigger = {"kind": kind, "failures": [], "advisory": []}
        if (op.startswith("on_") and kind is None) or op == "custom_request":
            result.skipped = (
                "trigger passthrough"
                if op.startswith("on_")
                else "unbounded custom request; requires a chosen endpoint"
            )
            continue
        if contract_errors:
            result.fixture_errors.extend(contract_errors)
            continue
        try:
            raw = dict(case["config"]) if case else sample(
                config_shapes(schema), config_shapes(member), examples=False, files=True
            )
        except Exception as exc:
            result.fixture_errors.append("Cannot generate config witness: " + reason(exc))
            continue
        if kind and not case:
            # A trigger's lifecycle fields (schedule, webhook id, registration mirrors) are NoClick's, never inputs.
            raw = {k: v for k, v in raw.items() if k not in triggers.PLUMBING}
        raw["operation"] = op
        raw = {**raw, **(config_overrides or {}).get(case_name, {})}
        result.config = raw
        case_credential = scenario_credential(credentials[op], case)
        try:
            witnesses = scenario_witnesses(case)
        except FixtureError as exc:
            result.fixture_errors.append(reason(exc))
            continue

        error_responses = []
        poll_reads = None

        def transport(request):
            try:
                body = request.content.decode("utf-8")
                body_encoding = "utf-8"
            except UnicodeDecodeError:
                body = base64.b64encode(request.content).decode("ascii")
                body_encoding = "base64"
            record = {
                "method": request.method,
                "url": str(request.url),
                "content_type": request.headers.get("content-type"),
                "body": body,
                "auth_placement": "header"
                if "authorization" in request.headers
                else None,
            }
            # Minimal httpx records keep their compact form. Full catalog runs
            # and the SDK adapters also retain headers, including AWS signatures.
            if FULL or request.extensions.get("conformance_transport"):
                record["headers"] = dict(request.headers)
            if body_encoding != "utf-8":
                record["body_encoding"] = body_encoding
            if "stripe-version" in request.headers:
                record["api_version"] = request.headers["stripe-version"]
            result.requests.append(record)
            try:
                matches = []
                postman_mismatches = []
                for index, candidate in enumerate(contracts):
                    try:
                        match = candidate.match(request)
                    except ValueError as exc:
                        if isinstance(candidate, PostmanContract):
                            postman_mismatches.append(str(exc))
                        continue
                    path = match[0]
                    matches.append(
                        (
                            (
                                # A collection cannot downgrade a route that
                                # also has an OpenAPI contract.
                                isinstance(candidate, PostmanContract),
                                path.count("{"),
                                -len(re.sub(r"\{[^}]+\}", "", path)),
                                index,
                            ),
                            candidate,
                            match,
                        )
                    )
                if not matches:
                    raise ValueError(
                        " / ".join(postman_mismatches)
                        if postman_mismatches
                        else f"No spec operation for {request.method} {request.url}"
                    )
                rank, selected, (path, method, operation) = min(
                    matches, key=lambda m: m[0]
                )
                spec_index = rank[-1]
            except Exception as exc:
                result.failures.append(reason(exc))
                raise
            contract = selected
            if isinstance(contract, PostmanContract):
                record["contract_format"] = "postman"
                record["postman_item"] = operation["item_id"]
                record["published_responses"] = len(operation["item"].get("response", []))
                if operation.get("host_bindings"):
                    record["host_bindings"] = operation["host_bindings"]
                ordinal = len(result.requests) - 1
                replay_base = (op, case_name, ordinal, spec_index, operation["item_id"])
                replayed.add((*replay_base, response_plan.get(ordinal, 0)))
                for example in range(record["published_responses"]):
                    replay_key = (*replay_base, example)
                    if replay_key not in replayed:
                        replayed.add(replay_key)
                        cases.append(
                            (op, member, case_name, case, {**response_plan, ordinal: example})
                        )
                record["response_example"] = response_plan.get(ordinal, 0)
            covered.add((spec_index, path, method))
            if len(contracts) > 1:
                record["spec_index"] = spec_index
            record["spec_operation"] = f"{method.upper()} {path}"
            record["security_declared"] = bool(
                contract.auth_override
                or operation.get("security", contract.doc.get("security", []))
            )
            if contract.auth_override is not None:
                record["auth_override"] = contract.auth_override
            try:
                for error in contract.request_errors(request, operation):
                    result.failures.append("request: " + reason(error))
            except FixtureError as exc:
                result.fixture_errors.append(reason(exc))
                raise
            except Exception as exc:
                result.failures.append("request: " + reason(exc))
            contract.scopes(node_cls, op, operation, result)
            try:
                response = contract.response(
                    request, operation, key=f"{method.upper()} {path}", record=record,
                    witnesses=witnesses,
                    strict_witnesses="witnesses" in case,
                    **(
                        {"example_index": response_plan.get(len(result.requests) - 1, 0)}
                        if isinstance(contract, PostmanContract) else {}
                    ),
                )
                record["response_status"] = response.status_code
                record["response_sha256"] = hashlib.sha256(response.content).hexdigest()
                if poll_reads is not None:
                    triggers.track_response(
                        response, poll_reads, f"{method.upper()} {path} response",
                        record.get("response_source"),
                    )
                if isinstance(contract, PostmanContract) and not 200 <= response.status_code < 300:
                    error_responses.append(response)
                return response
            except Exception as exc:
                result.fixture_errors.append(reason(exc))
                # Do not feed invalid fixtures to the node and blame its parser.
                raise

        try:
            config = model.model_validate({"config": raw, "credentials": case_credential})
        except Exception as exc:
            result.fixture_errors.append("Invalid config witness: " + reason(exc))
            continue
        try:
            node = node_cls(
                node_id="conformance",
                node_type=node_type,
                node_data={},
                config=config,
                sio=Mock(),
            )
            if kind == "webhook":
                if signing_error:
                    result.fixture_errors.append(signing_error)
                    continue
                with offline(), intercept_http(transport), resolved_offline():
                    result.trigger = await triggers.check_webhook(
                        node_cls, node_type, model, raw, case_credential,
                        trigger_events, signing, node_files,
                    )
                continue
            if kind == "poll":
                poll_reads = triggers.Reads(node_files)
                await triggers.seen_nothing(node)
            with offline(), intercept_http(transport), resolved_offline():
                output = await node.execute({})
                if kind == "poll":
                    result.trigger = triggers.check_poll(node_cls, node, output, poll_reads)
            expected_error = bool(error_responses)
            error_envelope = isinstance(output, dict) and (
                output.get("status") in ("error", "failed")
                or output.get("error")
                or output.get("ok") is False
            )
            if not result.fixture_errors:
                if expected_error and not error_envelope:
                    result.failures.append("node treated published error response as success")
                elif not expected_error and (output is None or error_envelope):
                    details = (
                        {k: output[k] for k in ("status", "error", "ok") if k in output}
                        if isinstance(output, dict) else output
                    )
                    result.failures.append(f"node error envelope: {details}")
            if not result.requests:
                result.failures.append("No HTTP request executed")
        except Exception as exc:
            if not result.fixture_errors and not result.failures:
                if not any(provider_rejection(exc, response) for response in error_responses):
                    result.failures.append("execution: " + reason(exc))
    if enrich:
        overrides = {}
        for result in results:
            # Catalog inputs are whole documented configurations. A parser
            # rejecting a synthetic response is no reason to replace their
            # identifiers/values with synthetic ones on an enriched rerun.
            if result.scenario is not None or result.operation in INPUTS:
                continue
            if not result.failures or result.fixture_errors:
                continue
            try:
                candidate = result.config
                for spec_index, contract in enumerate(contracts):
                    if isinstance(contract, PostmanContract):
                        continue
                    candidate = enrich_config(
                        contract,
                        by_operation[result.operation],
                        candidate,
                        [
                            r
                            for r in result.requests
                            if r.get("spec_index", 0) == spec_index
                        ],
                    )
            except Exception as exc:
                result.fixture_errors.append(
                    "Cannot generate input witness: " + reason(exc)
                )
                continue
            # A provider-valid value incompatible with the node model is a
            # node-schema finding, not an invalid fixture introduced by us.
            try:
                model.model_validate(
                    {
                        "config": candidate,
                        "credentials": scenario_credential(
                            credentials[result.operation],
                            INPUTS.get(result.scenario or result.operation, {}),
                        ),
                    }
                )
            except Exception:
                continue
            if candidate != result.config:
                overrides[result.scenario or result.operation] = candidate
        if overrides and not any(r.fixture_errors for r in results):
            return await run_provider(
                provider, config_overrides=overrides, enrich=False
            )
    return {
        "provider": provider,
        "node_type": node_type,
        "checked": sum(not r.skipped for r in results),
        "passed": sum(r.passed for r in results),
        "failed": sum(bool(r.failures) for r in results),
        "fixture_errors": sum(bool(r.fixture_errors) for r in results),
        "response_checked": sum(
            bool(r.requests) and all("response_status" in req for req in r.requests)
            for r in results
        ),
        "auth_checked": sum(
            bool(req.get("security_declared")) for r in results for req in r.requests
        ),
        "scope_checked": sum(r.scope_checks for r in results),
        "skipped": sum(bool(r.skipped) for r in results),
        "coverage": {
            "implemented": len(covered),
            "total": sum(len(c.paths) for c in contracts),
        },
        **(
            {"triggers": {
                "checked": sum(r.trigger is not None for r in results),
                "passed": sum(r.trigger is not None and r.passed for r in results),
            }}
            if any(r.trigger is not None for r in results) else {}
        ),
        **({"host_bindings": [
            {"spec_index": index, "variable": variable, **binding}
            for index, pin in enumerate(pins) if pin.get("format") == "postman"
            for variable, binding in pin.get("host_bindings", {}).items()
        ]} if any(pin.get("format") == "postman" and pin.get("host_bindings") for pin in pins) else {}),
        "operations": [dict(asdict(r), passed=r.passed) for r in results],
    }


def report_default(value):
    """Describe raw config bytes in JSON reports, never change executable inputs."""
    if isinstance(value, bytes):
        return {"encoding": "base64", "bytes": base64.b64encode(value).decode("ascii")}
    raise TypeError(
        f"Cannot serialize conformance report value: {type(value).__name__}"
    )


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=PROVIDERS, action="append")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on every node mismatch (reports by default)",
    )
    args = parser.parse_args()
    if not PROVIDERS:
        parser.error("no providers: set CONFORMANCE_CATALOG to a catalog folder")
    started = time.perf_counter()
    with offline():
        reports = [await run_provider(p) for p in args.provider or PROVIDERS]
    args.output.write_text(json.dumps(reports, indent=2, default=report_default) + "\n")
    for report in reports:
        print({k: v for k, v in report.items() if k != "operations"})
    print(f"Runtime: {time.perf_counter() - started:.2f}s")
    return int(
        any(r["fixture_errors"] or (args.strict and r["failed"]) for r in reports)
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
