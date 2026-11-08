"""Merge verdict for one integration from its conformance report and catalog. No model involved.

The integration merge gate merges a re-cut integration PR only when this verdict says ready (or postman-checked, for a
provider whose only published contract is a Postman collection), its CI is green and its scope check passes.

Blocking: an operation with no request checked, any request the spec rejects (unknown route, method, parameter, body),
a fixture error, a parser failure on a provider-authored response (docs or spec example), or a documented input or
response whose source page doesn't show it. Advisory: parser failures where only generated responses exist.
Postman evidence (a catalog pin with "format": "postman") never makes a verdict ready; complete Postman evidence gives
the separate state "postman-checked".

Usage (from backend): python -m tests.conformance.verdict REPORT.json CATALOG_DIR [--no-audit]
  -> prints JSON {provider, ready, blocking, advisory, stats} (plus state and operation_states for Postman catalogs).
The source audit fetches each documented input's and response's source page over the network and caches it under
$CONFORMANCE_PAGES (default ~/.cache/noclick-conformance/pages); --no-audit skips it and runs offline.
"""
import hashlib, json, os, re, sys
from pathlib import Path
import httpx
from html.parser import HTMLParser
from functools import lru_cache

CACHE = Path(os.environ.get("CONFORMANCE_PAGES") or Path.home() / ".cache/noclick-conformance/pages")


def leaves(value, out, keys=True):
    if isinstance(value, dict):
        for k, v in value.items():
            if keys:
                out.add(str(k))
            leaves(v, out, keys)
    elif isinstance(value, list):
        for v in value[:3]:
            leaves(v, out, keys)
    elif isinstance(value, str):
        # Only JSON documents are unpacked; scalar JSON strings remain literals.
        try:
            parsed = json.loads(value)
        except (ValueError, RecursionError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            leaves(parsed, out, keys)
        elif 3 <= len(value) <= 60:
            out.add(value)
    return out


def page(url):
    """A source page's text, fetched once and cached (the only network access, and only with the audit on)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / hashlib.sha256(url.encode()).hexdigest()[:24]
    if not f.exists():
        r = httpx.get(url, follow_redirects=True, timeout=30, headers={"User-Agent": "Mozilla/5.0 NoClick-conformance"})
        f.write_text(r.text)
    return f.read_text()


class PageText(HTMLParser):
    """Render fetched HTML without separating inline highlighting spans."""
    block_tags = {"address", "article", "aside", "blockquote", "br", "dd", "div",
                  "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form",
                  "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main",
                  "nav", "ol", "p", "pre", "section", "table", "td", "th", "tr", "ul"}

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.rendered = []

    def handle_starttag(self, tag, attrs):
        if tag in self.block_tags:
            self.rendered.append(" ")

    def handle_endtag(self, tag):
        if tag in self.block_tags:
            self.rendered.append(" ")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data):
        self.rendered.append(data)

    def handle_entityref(self, name):
        from html import unescape
        self.rendered.append(unescape("&" + name + ";"))

    def handle_charref(self, name):
        self.handle_entityref("#" + name)


@lru_cache(maxsize=8)
def page_forms(text):
    # JSON/YAML/Markdown source documents can themselves contain example HTML.
    # Those tags are literal documentation, not the surrounding page's markup.
    stripped = text.lstrip()
    plain_document = stripped.startswith(("{", "[", "#", ">", "---")) or bool(
        re.match(r"(?:openapi|swagger):", stripped)
    )
    if plain_document or not re.search(r"<!doctype\s+html|<(?:html|head|body|script|style|template|[a-z][a-z0-9]*)(?:\s[^<>]*|\s*)/?>", text, re.I):
        return text, re.sub(r"\s+", " ", text)
    parser = PageText()
    parser.feed(text)
    parser.close()
    return text, re.sub(r"\s+", " ", "".join(parser.rendered))


def matched(want, text):
    # Evidence is a union: preserve EVERY legacy raw-text match, and also
    # accept rendered text or a value's exact JSON-escaped spelling in either.
    raw, rendered = page_forms(text)
    found = set()
    for value in want:
        escaped = json.dumps(value)[1:-1]
        if (value in raw or re.sub(r"\s+", " ", value) in rendered
                or escaped in raw or re.sub(r"\s+", " ", escaped) in rendered):
            found.add(value)
    return found


def bound_url_shown(value, text):
    # A base can prefix a published endpoint, but not a different host/version.
    return any(
        re.search(re.escape(spelling) + r"(?![\w.~%+@:-])", form)
        for form in page_forms(text)
        for spelling in (value, json.dumps(value)[1:-1])
    )


def openapi_verdict(report, catalog, audit=True):
    report = report[0] if isinstance(report, list) else report
    catalog = Path(catalog)
    blocking, advisory = [], []
    stats = {"operations": 0, "skipped": 0, "request_ok": 0, "authored_parser_ok": 0, "generated_only": 0, "local_ok": 0}
    trigger_ops, passthrough = set(), set()
    for op in report["operations"]:
        name = op["operation"]
        if op.get("skipped"):
            if op["skipped"] == "trigger passthrough":
                passthrough.add(name)
            stats["skipped"] += 1
            continue
        stats["operations"] += 1
        trigger = op.get("trigger")
        if trigger:
            # A trigger's own checks (its events, new-item detection, agent event, field reads) always block: they
            # judge the node against the contract's schema, whatever produced the payload.
            trigger_ops.add(name)
            blocking.extend(f"{name}: trigger: {f[:200]}" for f in trigger.get("failures", []))
            advisory.extend(f"{name}: trigger: {a[:200]}" for a in trigger.get("advisory", []))
        if trigger and trigger.get("kind") == "webhook":
            # Judged by its deliveries, not by a request of its own; a registration request still meets the contract.
            if op.get("failures"):
                blocking.append(f"{name}: {op['failures'][0][:200]}")
            if op.get("fixture_errors"):
                blocking.append(f"{name}: fixture error: {op['fixture_errors'][0][:160]}")
            continue
        fails = op.get("failures", [])
        req_fail = [f for f in fails if f.startswith("request:") or "No spec operation" in f or "No route" in f]
        if not op.get("requests"):
            # This report-only attestation is emitted by the harness AFTER successful
            # execution of a local operation declared on the node class (see note).
            if op.get("node_local_ok") is True and not fails and not op.get("fixture_errors"):
                stats["local_ok"] += 1
                continue
            blocking.append(f"{name}: made no request the harness could check ({(fails or op.get('fixture_errors') or ['?'])[0][:160]})")
            continue
        if req_fail:
            blocking.append(f"{name}: " + req_fail[0][:200])
        else:
            stats["request_ok"] += 1
        if op.get("fixture_errors"):
            blocking.append(f"{name}: fixture error: {op['fixture_errors'][0][:160]}")
        parse_fail = [f for f in fails if f not in req_fail]
        sources = {r.get("response_source") for r in op["requests"] if r.get("response_status")}
        authored = sources and sources <= {"docs", "spec_example"}
        if not authored:
            stats["generated_only"] += 1
        if parse_fail:
            (blocking if authored else advisory).append(f"{name}: parser on {'provider-authored' if authored else 'generated'} response: {parse_fail[0][:180]}")
        elif authored:
            stats["authored_parser_ok"] += 1

    if audit:
        for kind, fname, getter in (("response", "witnesses.json", lambda e: e["body"]), ("input", "inputs.json", lambda e: e["config"]),
                                    ("event", "events.json", lambda e: e["body"])):
            path = catalog / fname
            if not path.exists():
                continue
            for key, entry in json.load(open(path)).items():
                src = entry.get("source")
                if not src or not str(src).startswith("http"):
                    blocking.append(f"{kind} {key}: no source URL")
                    continue
                try:
                    text = page(src)
                except Exception as exc:
                    blocking.append(f"{kind} {key}: source unreadable ({type(exc).__name__})")
                    continue
                # A documented response or event must show its keys and values; an input only its values (its keys are NoClick's
                # field names, and booleans or numbers are NoClick's own switches).
                want = {w for w in leaves(getter(entry), set(), keys=(kind != "input")) if w not in ("operation",)}
                found = matched(want, text)
                if want and len(found) / len(want) < 0.6:
                    blocking.append(f"{kind} {key}: only {len(found)}/{len(want)} of its keys and values appear on {src}")
    result = {"provider": report["provider"], "ready": not blocking, "blocking": blocking,
              "advisory": advisory, "stats": stats}
    if trigger_ops or passthrough:
        # Beside the operations: each trigger passed, failed, or (another family) wasn't checked.
        result["triggers"] = {
            **{name: "not checked: not a webhook or poll trigger" for name in sorted(passthrough - trigger_ops)},
            **{name: "failed" if any(b.startswith(name + ":") for b in blocking) else "passed"
               for name in sorted(trigger_ops)},
        }
    return result



def verdict(report, catalog, audit=True):
    """Postman evidence never grants an OpenAPI-ready verdict.

    Preserve the legacy object (including key order) for non-Postman catalogs.
    A mixed operation must satisfy both evidence bars independently.
    """
    import copy
    report = report[0] if isinstance(report, list) else report
    manifest = json.loads((Path(catalog) / "manifest.json").read_text())
    entry = manifest.get(report["provider"], {})
    pins = entry.get("specs", [entry])
    if not any(p.get("format") == "postman" for p in pins):
        result = openapi_verdict(report, catalog, audit)
        if report.get("host_bindings"):
            result["blocking"].append("Host bindings require a Postman collection pin")
            result.update(ready=False, state="not-ready")
        return result
    converted = copy.deepcopy(report)
    for op in converted["operations"]:
        for req in op.get("requests", []):
            if req.get("contract_format") == "postman" and req.get("response_source") == "postman_example":
                req["response_source"] = "spec_example"
    result = openapi_verdict(converted, catalog, audit)
    bindings = [
        {"spec_index": index, "variable": variable, **binding}
        for index, pin in enumerate(pins) if pin.get("format") == "postman"
        for variable, binding in pin.get("host_bindings", {}).items()
    ]
    if bindings or report.get("host_bindings"):
        from tests.conformance.postman import validate_host_bindings

        result["host_bindings"] = bindings
        if report.get("host_bindings") != bindings:
            result["blocking"].append("Postman host bindings differ between report and catalog")
        for binding in bindings:
            label = f"Postman host binding {binding['variable']} = {binding['value']} ({binding['source']})"
            try:
                validate_host_bindings({binding["variable"]: {
                    key: binding[key] for key in ("value", "source")
                }})
            except ValueError as exc:
                result["blocking"].append(f"{label}: {exc}")
                continue
            if audit:
                try:
                    text = page(binding["source"])
                except Exception as exc:
                    result["blocking"].append(f"{label}: source unreadable ({type(exc).__name__})")
                    continue
                if not bound_url_shown(binding["value"], text):
                    result["blocking"].append(f"{label}: source page does not show bound URL")
    # Preserve the original OpenAPI-only judgment for each operation. Converting
    # Postman sources must not turn a mixed operation's generated parser failure
    # into a weaker, advisory Postman result.
    groups, states = {}, {}
    for op in report["operations"]:
        if op.get("skipped"):
            continue
        groups.setdefault(op["operation"], []).append(op)
    used_postman = bool(bindings)
    for name, operations in groups.items():
        requests = [r for op in operations for r in op.get("requests", [])]
        postman = [r for r in requests if r.get("contract_format") == "postman"]
        if not postman:
            # A declared Postman-only catalog cannot accept legacy/generated
            # reports that lack Postman request and response attestations.
            if all(p.get("format") == "postman" for p in pins):
                result["blocking"].append(f"{name}: no checked Postman request evidence")
                states[name] = "not-ready"
            else:
                per_op = openapi_verdict({**report, "operations": operations}, catalog, False)
                states[name] = "ready" if per_op["ready"] else "not-ready"
            continue
        used_postman = True
        errors = []
        for op in operations:
            if op.get("failures") or op.get("fixture_errors") or not op.get("passed"):
                errors.append("Postman operation did not pass every node check")
        published, parsed = {}, {}
        for op in operations:
            for req in op.get("requests", []):
                if req.get("contract_format") != "postman":
                    continue
                index = req.get("spec_index", 0)
                for binding in req.get("host_bindings", []):
                    if {"spec_index": index, **binding} not in bindings:
                        errors.append("request host binding is not declared by its Postman pin")
                if index >= len(pins) or pins[index].get("format") != "postman":
                    errors.append("Postman evidence does not identify a Postman pin")
                key = (index, req.get("postman_item"))
                count = req.get("published_responses", 0)
                if not isinstance(count, int) or count < 1:
                    errors.append("no published example response")
                    continue
                if key in published and published[key] != count:
                    errors.append("inconsistent published example counts")
                published[key] = count
                example = req.get("response_example")
                if (req.get("response_source") != "postman_example"
                        or not req.get("response_status") or not req.get("response_sha256")):
                    errors.append("missing verbatim Postman response evidence")
                elif op.get("passed") and isinstance(example, int) and 0 <= example < count:
                    parsed.setdefault(key, set()).add(example)
        for key, count in published.items():
            missing = set(range(count)) - parsed.get(key, set())
            if missing:
                errors.append(f"saved Postman responses not parsed: item {key[1]} examples {sorted(missing)}")
        # OpenAPI requests in a mixed operation still need the original bar;
        # Postman failure classification above is always blocking.
        for error in dict.fromkeys(errors):
            result["blocking"].append(f"{name}: {error}")
        prior = any(b.startswith(name + ":") for b in result["blocking"])
        states[name] = "not-ready" if errors or prior else "postman-checked"
    if not groups:
        result["blocking"].append("no checked operations for Postman catalog")
    result["ready"] = not result["blocking"] and not used_postman
    result["state"] = "not-ready" if result["blocking"] else "postman-checked" if used_postman else "ready"
    result["operation_states"] = states
    return result

if __name__ == "__main__":
    report = json.loads(Path(sys.argv[1]).read_text())
    print(json.dumps(verdict(report, sys.argv[2], "--no-audit" not in sys.argv), indent=1))
