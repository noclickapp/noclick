"""Pinned Postman requests and verbatim saved responses, never inferred schemas."""
from __future__ import annotations

import base64
import json
import re
from email.parser import BytesParser
from email.policy import default
from urllib.parse import parse_qsl, quote, urlsplit

import httpx
import tldextract

SCHEMAS = {
    f"https://schema.getpostman.com/json/collection/v{version}/collection.json"
    for version in ("2.0.0", "2.1.0")
}
VARIABLE = re.compile(r"\{\{([^{}]+)\}\}")
# Use the packaged PSL, including private suffixes, without fetching updates.
DOMAIN = tldextract.TLDExtract(
    suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True
)
DOCS_HOSTS = {
    "apis.guru",
    "postman.com",
    "getpostman.com",
    "readme.io",
    "github.io",
    "gitbook.io",
    "gitbook.com",
    "stoplight.io",
    "swaggerhub.com",
    "swaggerhub.io",
}


def validate_host_bindings(bindings):
    if not isinstance(bindings, dict):
        raise ValueError("Postman host_bindings must be an object")
    for variable, binding in bindings.items():
        if not isinstance(variable, str) or not variable or VARIABLE.search(variable):
            raise ValueError("Postman host binding requires a variable name")
        if not isinstance(binding, dict) or set(binding) != {"value", "source"}:
            raise ValueError("Postman host binding requires value and source")
        domains = []
        for key in ("value", "source"):
            raw = binding[key]
            if not isinstance(raw, str):
                raise ValueError("Postman host binding requires absolute https URLs")
            url = urlsplit(raw)
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username is not None
                or url.password is not None
                or url.fragment
                or VARIABLE.search(raw)
                or any(c.isspace() for c in raw)
                or "\\" in raw
                or (key == "value" and url.query)
            ):
                raise ValueError("Postman host binding requires absolute https URLs")
            url.port  # Reject malformed ports before matching a request.
            host = url.hostname.rstrip(".").encode("idna").decode("ascii").lower()
            domain = DOMAIN(host)
            if (
                not domain.suffix
                or not domain.domain
                or any(
                    host == blocked or host.endswith("." + blocked)
                    for blocked in DOCS_HOSTS
                )
            ):
                raise ValueError(
                    "Postman host binding source must be on the provider's own domain"
                )
            domains.append(domain.top_domain_under_public_suffix)
        if domains[0] != domains[1]:
            raise ValueError(
                "Postman host binding source must be on the provider's own domain"
            )
    return bindings


def is_postman(doc):
    return isinstance(doc, dict) and doc.get("info", {}).get("schema") in SCHEMAS


def validate_collection(doc):
    if not is_postman(doc) or not isinstance(doc.get("item"), list):
        raise ValueError("Expected a Postman Collection v2.0 or v2.1 document")


def enabled(rows):
    return [row for row in rows or [] if not row.get("disabled")]


def text_pattern(value):
    # Template values remain unconstrained, but literal header prefixes do not.
    parts = re.split(r"(\{\{[^{}]+\}\}|<[^<>]+>)", str(value))
    return "".join(".+" if p.startswith(("{{", "<")) else re.escape(p) for p in parts)


def field_paths(value, prefix=()):
    """Keys at their exact nesting; array indexes are not field names."""
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            path = (*prefix, key)
            found.add(path)
            found.update(field_paths(child, path))
    elif isinstance(value, list):
        for child in value:
            found.update(field_paths(child, (*prefix, "[]")))
    return found


def request_json(raw):
    """Read request keys even when a Postman value is an unquoted variable.

    Only request evidence is inspected here. Published responses never pass
    through this function and their bytes are never substituted.
    """
    out, in_string, escaped, index = [], False, False, 0
    while index < len(raw):
        char = raw[index]
        variable = VARIABLE.match(raw, index) if not in_string else None
        if variable:
            out.append(json.dumps(variable[0]))
            index = variable.end()
            continue
        out.append(char)
        if char == '"' and not escaped:
            in_string = not in_string
        escaped = char == "\\" and not escaped
        index += 1
    return json.loads("".join(out))


def auth_values(auth, kind):
    values = auth.get(kind, [])
    return (
        values
        if isinstance(values, dict)
        else {p["key"]: p.get("value") for p in values}
    )


def published_body(body):
    body = body or {}
    mode = body.get("mode")
    if not body or not mode:
        return None, set()
    if mode == "raw":
        raw = body.get("raw", "")
        try:
            return "json", field_paths(request_json(raw))
        except ValueError:
            return "raw", set()
    if mode in {"urlencoded", "formdata"}:
        return mode, {(row["key"],) for row in enabled(body.get(mode))}
    raise ValueError(f"Unsupported Postman request body mode: {mode}")


class PostmanContract:
    def __init__(
        self,
        doc,
        *,
        auth_override=None,
        server_url=None,
        server_variables=None,
        host_bindings=None,
    ):
        validate_collection(doc)
        self.doc = doc
        self.auth_override = auth_override
        self.paths = []
        self.host_bindings = validate_host_bindings(
            {} if host_bindings is None else host_bindings
        )

        def refuse_defined(value):
            if isinstance(value, dict):
                for row in enabled(value.get("variable")):
                    if (
                        row["key"] in self.host_bindings
                        and row.get("value") is not None
                        and str(row["value"]).strip()
                    ):
                        raise ValueError(
                            f"Postman host binding refuses defined variable: {row['key']}"
                        )
                for child in value.values():
                    refuse_defined(child)
            elif isinstance(value, list):
                for child in value:
                    refuse_defined(child)

        if self.host_bindings:
            refuse_defined(doc)
        used_bindings = set()

        # Catalog credentials/server_url cannot invent an undocumented host.
        def walk(items, variables, auth, trail=()):
            for index, item in enumerate(items):
                identity = (*trail, index)
                local = {
                    **variables,
                    **{
                        v["key"]: str(v.get("value", ""))
                        for v in enabled(item.get("variable"))
                    },
                }
                inherited = item.get("auth", auth)
                if "request" in item:
                    req = item["request"]
                    if not isinstance(req, dict):
                        raise ValueError("Postman request must be an object")
                    used = []
                    path, origin, query = self.url(req, local, self.host_bindings, used)
                    regex = re.compile(
                        "^"
                        + "/".join(
                            "[^/]+" if re.fullmatch(r":[^/]+|\{\{[^{}]+\}\}", segment)
                            # Postman encodes literal braces; only :name and
                            # {{name}} are variables, never single {name}.
                            else re.escape(quote(segment, safe="!$&'()*+,-.:;=@_%~"))
                            for segment in path.split("/")
                        )
                        + "$"
                    )
                    op = {
                        "item": item,
                        "item_id": "/".join(map(str, identity)),
                        "origin": origin,
                        "query": query,
                        "auth": req.get("auth", inherited),
                        "security": bool(req.get("auth", inherited)),
                    }
                    if used:
                        op["host_bindings"] = used
                        used_bindings.update(b["variable"] for b in used)
                    canonical = re.sub(
                        r"\{\{([^{}]+)\}\}|:([^/]+)",
                        lambda m: "{" + (m[1] or m[2]) + "}",
                        path,
                    )
                    self.paths.append((canonical, req["method"].lower(), regex, op))
                walk(item.get("item", []), local, inherited, identity)

        variables = {
            v["key"]: str(v.get("value", "")) for v in enabled(doc.get("variable"))
        }
        walk(doc["item"], variables, doc.get("auth"))
        if set(self.host_bindings) - used_bindings:
            raise ValueError(
                "Postman host binding variable is not an undefined request host"
            )

    @staticmethod
    def url(req, variables, host_bindings=None, used=None):
        url = req.get("urlObject", req.get("url"))
        if isinstance(url, dict) and "host" in url:
            host = url["host"]
            host = ".".join(host) if isinstance(host, list) else host
            path = url.get("path", [])
            path = "/".join(path) if isinstance(path, list) else path.lstrip("/")
            raw = host + "/" + path
            if url.get("protocol") and "://" not in raw:
                raw = url["protocol"] + "://" + raw
            if url.get("port"):
                raw = raw.replace(host, host + ":" + str(url["port"]), 1)
            query = {r["key"] for r in enabled(url.get("query"))}
        else:
            raw = url.get("raw", "") if isinstance(url, dict) else url or ""
            # A collection can carry the request line in its URL ("GET https://…", Dux-Soup's Read User Settings):
            # the item's own method and a space before it are that method, never part of the URL.
            method = str(req.get("method", "")).upper()
            if method and raw[: len(method) + 1].upper() == method + " ":
                raw = raw[len(method) :].lstrip()
            raw, _, q = raw.partition("?")
            query = {k for k, _ in parse_qsl(q, keep_blank_values=True)}
        # Only base/host variables are expanded. Path segments remain variables,
        # even when Postman publishes a sample value for them.
        head, slash, tail = raw.partition("/")
        if raw.startswith(("http://", "https://")):
            scheme, rest = raw.split("://", 1)
            head, slash, tail = rest.partition("/")
            head = scheme + "://" + head
        for _ in range(20):
            expanded = VARIABLE.sub(
                lambda m: m[0]
                if host_bindings and m[1] in host_bindings
                else variables.get(m[1], m[0]),
                head,
            )
            if expanded == head:
                break
            head = expanded
        names = list(dict.fromkeys(VARIABLE.findall(head)))
        bindings = host_bindings or {}
        if names and any(name in bindings for name in names):
            if not all(name in bindings for name in names):
                raise ValueError("Postman bound host still has undefined variables")
            values = {bindings[name]["value"] for name in names}
            if len(values) != 1:
                raise ValueError(
                    "Postman bindings for one host must agree on its base URL"
                )
            value = values.pop()
            # Whole base variables can include a base path; an embedded host
            # variable must preserve every literal host character and scheme.
            if not re.fullmatch(r"(?:https://)?\{\{[^{}]+\}\}", head):
                target = value if "://" in head else value.removeprefix("https://")
                pattern = "".join(
                    "[^/:]+" if VARIABLE.fullmatch(part) else re.escape(part)
                    for part in re.split(r"(\{\{[^{}]+\}\})", head)
                )
                if not re.fullmatch(pattern, target):
                    raise ValueError(
                        "Postman binding changes literal host or introduces a path beyond the base"
                    )
            head = value.rstrip("/")
            if used is not None:
                used.extend({"variable": name, **bindings[name]} for name in names)
        raw = head + ("/" + tail if slash else "")
        if "://" not in raw and not raw.startswith(("/", "{{")):
            raw = "https://" + raw
        parsed = urlsplit(raw)
        valid = (
            parsed.scheme in {"http", "https"}
            and parsed.netloc
            and not VARIABLE.search(parsed.netloc)
            and not parsed.username
        )
        origin = (
            (
                parsed.scheme,
                parsed.hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
            )
            if valid
            else None
        )
        path = parsed.path or "/"
        return path, origin, query

    def match(self, request):
        origin = (
            request.url.scheme,
            request.url.host,
            request.url.port or (443 if request.url.scheme == "https" else 80),
        )
        path = request.url.raw_path.split(b"?", 1)[0].decode("ascii")
        matches = [
            (p, m, op)
            for p, m, regex, op in self.paths
            if m == request.method.lower()
            and op["origin"] == origin
            and regex.fullmatch(path)
        ]
        if not matches:
            literal_host = any(
                op["origin"] and re.search(r"[{}]", op["origin"][1])
                for _, _, _, op in self.paths
            )
            raise ValueError(
                f"No spec operation for {request.method} {request.url} (Postman host/path/method)"
                + (
                    "; single-brace hosts are literal in Postman, not substitutable variables"
                    if literal_host
                    else ""
                )
            )
        # Collections may have several items on one RPC route. Choose an item
        # accepting the whole request, never a union of unrelated items.
        return min(
            matches, key=lambda match: len(list(self.request_errors(request, match[2])))
        )

    def request_errors(self, request, operation):
        req = operation["item"]["request"]
        examples = operation["item"].get("response", [])
        originals = [r.get("originalRequest", {}) for r in examples]
        headers = enabled(req.get("header"))
        auth = operation.get("auth") or {}
        auth_query = set()
        if auth.get("type") == "apikey":
            settings = auth_values(auth, "apikey")
            if settings.get("in") == "query":
                auth_query.add(settings.get("key"))
        extra_query = set(request.url.params) - operation["query"] - auth_query
        if extra_query:
            yield ValueError(f"Undocumented Postman query keys: {sorted(extra_query)}")
        for header in headers:
            name = header["key"]
            if name.lower() in {"authorization", "content-type"}:
                continue
            if not any(
                value.strip()
                and re.fullmatch(text_pattern(header.get("value", "")), value)
                for value in request.headers.get_list(name)
            ):
                yield ValueError(f"Missing or incorrect Postman header: {name}")
        # An auth/media declaration in a saved original request is evidence too.
        for name in ("authorization", "content-type"):
            declared = [h for h in headers if h["key"].lower() == name]
            if not declared:
                declared = [
                    h
                    for original in originals
                    for h in enabled(original.get("header"))
                    if h["key"].lower() == name
                ]
            if declared and not any(
                re.fullmatch(
                    text_pattern(h.get("value", "")),
                    request.headers.get(name, ""),
                    re.I,
                )
                for h in declared
            ):
                yield ValueError(
                    f"Postman {'Authentication' if name == 'authorization' else 'media type'} missing or incorrect: {name}"
                )
        auth = operation.get("auth")
        # A catalog override can supply missing auth evidence, but cannot
        # replace authentication explicitly declared by the collection.
        if self.auth_override is not None and not auth:
            if not self.auth_override.get("source", "").startswith(
                ("https://", "http://")
            ):
                raise ValueError("Authentication override requires documentation URL")
            auth = {"type": "override"}
        if auth and auth.get("type") != "noauth":
            kind = auth["type"]
            value = request.headers.get("authorization", "")
            if kind in {"bearer", "oauth2", "basic", "override"}:
                scheme = (
                    self.auth_override["scheme"]
                    if kind == "override"
                    else "Bearer"
                    if kind in {"bearer", "oauth2"}
                    else "Basic"
                )
                valid = bool(
                    re.fullmatch(re.escape(scheme) + r" .+", value, re.I)
                    and value.split(" ", 1)[1].strip()
                )
                if kind == "basic" and valid:
                    try:
                        valid = (
                            ":"
                            in base64.b64decode(
                                value.split(" ", 1)[1], validate=True
                            ).decode()
                        )
                    except (ValueError, UnicodeError):
                        valid = False
            elif kind == "apikey":
                settings = auth_values(auth, "apikey")
                location = settings.get("in", "header")
                if location not in {"header", "query"}:
                    raise ValueError(f"Unsupported Postman auth location: {location}")
                valid = bool(
                    (
                        request.headers if location == "header" else request.url.params
                    ).get(settings["key"])
                )
            else:
                raise ValueError(f"Unsupported Postman auth: {kind}")
            if not valid:
                yield ValueError(
                    "Authentication is missing or in the wrong location/scheme"
                )
        allowed, modes = set(), set()
        for original in [req, *originals]:
            mode, fields = published_body(original.get("body", {}))
            if mode:
                modes.add(mode)
                allowed.update(fields)
        if request.content:
            media = (
                request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            )
            try:
                form_mode = {
                    "application/x-www-form-urlencoded": "urlencoded",
                    "multipart/form-data": "formdata",
                }.get(media)
                if (
                    ("json" in modes and form_mode not in modes)
                    or media == "application/json"
                    or media.endswith("+json")
                ):
                    actual = field_paths(json.loads(request.content))
                    if "json" not in modes:
                        raise ValueError("No published JSON request body")
                elif (
                    media == "application/x-www-form-urlencoded"
                    and "urlencoded" in modes
                ):
                    actual = {
                        (k,)
                        for k, _ in parse_qsl(
                            request.content.decode(), keep_blank_values=True
                        )
                    }
                elif media == "multipart/form-data" and "formdata" in modes:
                    message = BytesParser(policy=default).parsebytes(
                        b"Content-Type: "
                        + request.headers["content-type"].encode()
                        + b"\r\n\r\n"
                        + request.content
                    )
                    if not message.is_multipart():
                        raise ValueError("Invalid multipart body")
                    names = [
                        part.get_param("name", header="content-disposition")
                        for part in message.iter_parts()
                    ]
                    if any(name is None for name in names):
                        raise ValueError("Multipart field has no name")
                    actual = {(name,) for name in names}
                else:
                    # Unstructured raw bodies have no field contract. They must
                    # be sent as published, rather than accepting arbitrary data.
                    raws = [
                        (o.get("body") or {}).get("raw", "") for o in [req, *originals]
                    ]
                    if not any(
                        re.fullmatch(text_pattern(raw), request.content.decode())
                        for raw in raws
                        if raw
                    ):
                        raise ValueError(
                            "No published request body for this media type"
                        )
                    actual = set()
                absent = actual - allowed
                if absent:
                    yield ValueError(
                        f"Undocumented Postman body fields: {sorted('.'.join(p) for p in absent)}"
                    )
            except (ValueError, UnicodeError) as exc:
                yield ValueError(f"Postman body: {exc}")

    def validate_request(self, request):
        errors = list(self.request_errors(request, self.match(request)[2]))
        if errors:
            raise ValueError(" / ".join(map(str, errors)))

    def response(self, request, operation, *, record=None, example_index=0, **kwargs):
        from tests.conformance.harness import FixtureError

        responses = operation["item"].get("response", [])
        if not responses:
            raise FixtureError("no published example response")
        if not 0 <= example_index < len(responses):
            raise FixtureError("Postman response example index out of range")
        example = responses[example_index]
        if (
            not isinstance(example.get("code"), int)
            or not 100 <= example["code"] <= 599
        ):
            raise FixtureError("Postman example has no valid published status")
        body = example.get("body")
        if body is not None and not isinstance(body, str):
            raise FixtureError("Postman example body must be published text")
        # No JSON reserialization, MIME inference, placeholder interpolation,
        # status filtering, or generated fallback. Postman saves decoded text,
        # not the encoded wire entity. Do not ask clients to decompress it again
        # or frame it using the original compressed/otherwise stale length.
        content = (body or "").encode("utf-8")
        headers = [
            (h["key"], h["value"])
            for h in example.get("header", [])
            if h["key"].lower() != "content-encoding"
            and not (
                h["key"].lower() == "content-length" and h["value"] != str(len(content))
            )
        ]
        # All other headers, including duplicate values, remain as published.
        response = httpx.Response(
            example["code"],
            content=content,
            headers=headers,
            request=request,
        )
        if record is not None:
            record["response_source"] = "postman_example"
            record["response_example"] = example_index
        return response

    def scopes(self, node_cls, operation_name, operation, result):
        # Postman declares no OAuth scope requirements; this is weaker evidence.
        return
