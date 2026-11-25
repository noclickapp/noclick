"""What an app's ``noclick.json`` says it needs, and a wrangler config's equivalents, as ``noclick deploy`` reads them.

Beside what the build reads (``root``, ``node``, ``build_env``, ``account_key``, ``secrets``), ``noclick.json`` names
what the app is given before it runs::

    {
      "bindings": {"DB": {"database": "booking-db"}, "FILES": {"bucket": "uploads"},
                   "SEEN": {"dict": "seen-orders"}, "JOBS": {"queue": "webhook-buffer"}},
      "env": {"PUBLIC_BASE_URL": "https://book.acme.com"},
      "crons": [{"cron": "0 9 * * 1-5", "path": "/jobs/reminders", "tz": "America/New_York"}]
    }

``noclick deploy`` makes each binding's resource when it's missing (in the app's region) and binds it, sets each
setting, and adds or updates each schedule, saying what it changed, before it ships the code. A deploy made any other
way (a push, the API) fails naming what the app lacks, so nothing in the file is ever dropped.

A Workers project's wrangler config says some of the same in Cloudflare's terms: its ``vars``, ``d1_databases``,
``kv_namespaces``, ``r2_buckets``, ``queues.producers`` and ``triggers.crons`` are written into ``noclick.json`` as the
NoClick equivalents (a D1 database a NoClick database, a KV namespace a dict, an R2 bucket a bucket), each said.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

NOCLICK_JSON = "noclick.json"
WRANGLER_FILES = ("wrangler.jsonc", "wrangler.json", "wrangler.toml")
# What a resource binding names, and the SDK class that makes it.
KINDS = ("database", "bucket", "dict", "queue")
# A cron a wrangler config gives a Worker's scheduled() handler, which NoClick never calls: the path it POSTs instead.
SCHEDULED_PATH = "/__scheduled"
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_RESOURCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
_CRON_FIELDS = 5
_OPTIONS = {"database": ("engine",), "bucket": ("public",), "dict": (), "queue": ()}


class ConfigError(ValueError):
    """A file that says something a deploy can't do: what, and what to change."""

    def __init__(self, message: str, next_step: str) -> None:
        super().__init__(message)
        self.message, self.next_step = message, next_step


@dataclass(frozen=True)
class BindingSpec:
    name: str
    kind: str
    resource: str
    options: Tuple[Tuple[str, Any], ...] = ()

    def said(self) -> str:
        return f"{self.name} → {self.kind} {self.resource}"


@dataclass(frozen=True)
class CronSpec:
    cron: str
    path: str
    tz: str = "UTC"
    name: Optional[str] = None

    @property
    def key(self) -> str:
        """What keys it among the app's schedules (as ``Project.schedule`` keys it)."""
        return self.name or self.path

    def said(self) -> str:
        return f"{self.cron} ({self.tz}) → POST {self.path}"


@dataclass
class AppConfig:
    """What ``noclick.json`` asks the app be given (``present``: whether the folder has one)."""

    bindings: List[BindingSpec] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    crons: List[CronSpec] = field(default_factory=list)
    present: bool = False
    raw: Dict[str, Any] = field(default_factory=dict)
    root: Optional[str] = None

    @property
    def empty(self) -> bool:
        return not (self.bindings or self.env or self.crons)


# --- reading ---------------------------------------------------------------------------------------------------


def _bad(what: str, example: str) -> ConfigError:
    return ConfigError(f"{NOCLICK_JSON}'s {what}", f"Fix it ({example}), then deploy again.")


def parse(raw: Dict[str, Any]) -> AppConfig:
    """``noclick.json``'s bindings, env and crons, refused (``ConfigError``) where they're the wrong shape."""
    config = AppConfig(present=True, raw=raw, root=raw.get("root") if isinstance(raw.get("root"), str) else None)
    bindings = raw.get("bindings") or {}
    if not isinstance(bindings, dict):
        raise _bad("bindings is an object of names, not a list", '"bindings": {"DB": {"database": "booking-db"}}')
    for name, spec in bindings.items():
        config.bindings.append(_binding(name, spec))
    env = raw.get("env") or {}
    if not isinstance(env, dict):
        raise _bad("env is an object of names and values", '"env": {"PUBLIC_BASE_URL": "https://book.acme.com"}')
    for name, value in env.items():
        if not _NAME.match(name):
            raise _bad(f"env names {name!r}: a name is letters, digits and _, starting with a letter",
                       '"env": {"PUBLIC_BASE_URL": "..."}')
        if not isinstance(value, str):
            raise _bad(f"env.{name} is {json.dumps(value)}: a setting is text", f'"{name}": "{json.dumps(value)}"')
        config.env[name] = value
    crons = raw.get("crons") or []
    if not isinstance(crons, list):
        raise _bad("crons is a list", '"crons": [{"cron": "0 * * * *", "path": "/jobs/hourly"}]')
    for i, spec in enumerate(crons):
        config.crons.append(_cron(i, spec))
    keys = [c.key for c in config.crons]
    twice = sorted({k for k in keys if keys.count(k) > 1})
    if twice:
        raise _bad(f"crons has two on {twice[0]}: give each a name of its own",
                   f'"name": "{twice[0].strip("/").replace("/", "-") or "root"}-2"')
    return config


def _binding(name: Any, spec: Any) -> BindingSpec:
    example = '"DB": {"database": "booking-db"}'
    if not isinstance(name, str) or not _NAME.match(name):
        raise _bad(f"bindings names {name!r}: a binding is letters, digits and _, starting with a letter", example)
    if not isinstance(spec, dict):
        raise _bad(f"bindings.{name} is an object naming one of {', '.join(KINDS)}", example)
    kinds = [k for k in KINDS if k in spec]
    if len(kinds) != 1:
        raise _bad(f"bindings.{name} names {' and '.join(kinds) or 'none'} of {', '.join(KINDS)}: name one",
                   f'"{name}": {{"database": "{name.lower()}"}}')
    kind = kinds[0]
    resource = spec[kind]
    extra = sorted(set(spec) - {kind, *_OPTIONS[kind]})
    if extra:
        allowed = ", ".join(_OPTIONS[kind]) or "nothing else"
        raise _bad(f"bindings.{name} names {', '.join(extra)}, which a {kind} binding doesn't take ({allowed})",
                   f'"{name}": {{"{kind}": "{resource}"}}')
    if not isinstance(resource, str) or not _RESOURCE.match(resource):
        raise _bad(f"bindings.{name}.{kind} is the {kind}'s name (letters, digits, . _ -), not {json.dumps(resource)}",
                   f'"{name}": {{"{kind}": "{name.lower().replace("_", "-")}"}}')
    options = tuple((k, spec[k]) for k in _OPTIONS[kind] if k in spec)
    if kind == "database" and dict(options).get("engine", "sqlite") not in ("sqlite", "postgres"):
        raise _bad(f"bindings.{name}.engine is sqlite or postgres", f'"{name}": {{"database": "{resource}", '
                                                                   '"engine": "postgres"}')
    if kind == "bucket" and not isinstance(dict(options).get("public", False), bool):
        raise _bad(f"bindings.{name}.public is true or false", f'"{name}": {{"bucket": "{resource}", "public": true}}')
    return BindingSpec(name, kind, resource, options)


def _cron(i: int, spec: Any) -> CronSpec:
    example = '{"cron": "0 * * * *", "path": "/jobs/hourly"}'
    if not isinstance(spec, dict):
        raise _bad(f"crons[{i}] is an object", example)
    extra = sorted(set(spec) - {"cron", "path", "tz", "name"})
    if extra:
        raise _bad(f"crons[{i}] names {', '.join(extra)}: a cron takes cron, path, tz and name", example)
    cron, path = spec.get("cron"), spec.get("path")
    if not isinstance(cron, str) or len(cron.split()) != _CRON_FIELDS:
        raise _bad(f"crons[{i}].cron is five fields (minute hour day month weekday), not {json.dumps(cron)}", example)
    if not isinstance(path, str) or not path.startswith("/"):
        raise _bad(f"crons[{i}].path is the path NoClick POSTs on each tick, starting with /, not "
                   f"{json.dumps(path)}", example)
    tz, name = spec.get("tz", "UTC"), spec.get("name")
    if not isinstance(tz, str) or not tz:
        raise _bad(f"crons[{i}].tz is a timezone (America/New_York) or user", example)
    if name is not None and (not isinstance(name, str) or not name):
        raise _bad(f"crons[{i}].name is text", example)
    return CronSpec(" ".join(cron.split()), path, tz, name)


def read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as bad:
        raise ConfigError(f"{path.name} isn't valid JSON ({bad}).", f"Fix {path.name}, then deploy again.") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} is a JSON object, not {type(data).__name__}.",
                          f"Fix {path.name}, then deploy again.")
    return data


def read_config(root: Path) -> AppConfig:
    """``noclick.json`` at ``root`` (the repository's root), or an empty one when there's none."""
    path = root / NOCLICK_JSON
    return parse(read_json(path)) if path.is_file() else AppConfig()


# --- wrangler configs ------------------------------------------------------------------------------------------


def strip_jsonc(text: str) -> str:
    """JSONC as JSON: comments and trailing commas out, strings untouched."""
    out: List[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        else:
            out.append(c)
            i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def find_wrangler(folder: Path) -> Optional[Path]:
    return next((folder / name for name in WRANGLER_FILES if (folder / name).is_file()), None)


def read_wrangler(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix == ".toml":
        try:
            import tomllib  # type: ignore[import-not-found]
        except ImportError:
            raise ConfigError(f"{path.name} is TOML, which this Python can't read (3.11 has tomllib).",
                              "Run noclick on Python 3.11 or later, or write the config as wrangler.jsonc.") from None
        try:
            return tomllib.loads(text)
        except ValueError as bad:
            raise ConfigError(f"{path.name} isn't valid TOML ({bad}).", f"Fix {path.name}, then deploy again.") \
                from None
    try:
        data = json.loads(strip_jsonc(text))
    except ValueError as bad:
        raise ConfigError(f"{path.name} isn't valid JSON ({bad}).", f"Fix {path.name}, then deploy again.") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} is an object.", f"Fix {path.name}, then deploy again.")
    return data


def _resource_name(text: str) -> str:
    """A NoClick resource name from a Cloudflare one or a binding (``SESSION_KV`` → ``session-kv``)."""
    name = re.sub(r"[^a-z0-9._-]+", "-", text.lower()).strip("-._")
    return name[:63] or "data"


def _entries(value: Any) -> List[Dict[str, Any]]:
    items = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
    return [item for item in items if isinstance(item, dict)]


@dataclass
class Translation:
    """What a wrangler config said in Cloudflare's terms, as ``noclick.json`` says it: ``added`` (each in words),
    what ``noclick.json`` already said its own way (``kept``), and what's left for the app's code and config to
    change before NoClick's build takes it (``left``: each key still in the wrangler config, and what to do)."""

    file: str
    added: List[str] = field(default_factory=list)
    kept: List[str] = field(default_factory=list)
    left: List[Tuple[str, str]] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return bool(self.added)


def translate(wrangler: Dict[str, Any], file: str, raw: Dict[str, Any]) -> Translation:
    """``raw`` (``noclick.json``'s data) with what ``wrangler`` says that it doesn't, and what's left to change."""
    done = Translation(file, config=json.loads(json.dumps(raw)))
    bindings: Dict[str, Any] = dict(done.config.get("bindings") or {})
    env: Dict[str, Any] = dict(done.config.get("env") or {})
    crons: List[Any] = list(done.config.get("crons") or [])

    def bind(name: str, kind: str, resource: str, source: str) -> None:
        if not name:
            return
        if name in bindings:
            have = bindings[name]
            if not (isinstance(have, dict) and have.get(kind) == resource):
                done.kept.append(f"bindings.{name} as {NOCLICK_JSON} has it ({file}'s {source} names {kind} "
                                 f"{resource})")
            return
        bindings[name] = {kind: resource}
        done.added.append(f"bindings.{name} → {kind} {resource} (from {source})")

    for entry in _entries(wrangler.get("d1_databases")):
        name = str(entry.get("binding") or "")
        bind(name, "database", _resource_name(str(entry.get("database_name") or name)), "d1_databases")
    worker = wrangler.get("name") if isinstance(wrangler.get("name"), str) else ""
    for entry in _entries(wrangler.get("kv_namespaces")):
        name = str(entry.get("binding") or "")
        # A namespace has only an id: its dict is named after the worker too, so two apps' CACHE never share one.
        bind(name, "dict", _resource_name(f"{worker}-{name}" if worker else name), "kv_namespaces")
    for entry in _entries(wrangler.get("r2_buckets")):
        name = str(entry.get("binding") or "")
        bind(name, "bucket", _resource_name(str(entry.get("bucket_name") or name)), "r2_buckets")
    queues = wrangler.get("queues")
    for entry in _entries(queues.get("producers") if isinstance(queues, dict) else None):
        name = str(entry.get("binding") or "")
        bind(name, "queue", _resource_name(str(entry.get("queue") or name)), "queues.producers")

    variables = wrangler.get("vars")
    for name, value in (variables.items() if isinstance(variables, dict) else ()):
        text = value if isinstance(value, str) else json.dumps(value)
        if name in env:
            if env[name] != text:
                done.kept.append(f"env.{name} as {NOCLICK_JSON} has it ({file}'s vars set {clip(text)})")
            continue
        env[name] = text
        done.added.append(f"env.{name} = {clip(text)} (from vars)")

    triggers = wrangler.get("triggers")
    expressions = [str(c) for c in ((triggers or {}).get("crons") or ()) if c] if isinstance(triggers, dict) else []
    held = {c.get("cron") for c in crons if isinstance(c, dict)}
    for i, expression in enumerate(expressions):
        if " ".join(expression.split()) in held:
            continue
        entry = {"cron": " ".join(expression.split()), "path": SCHEDULED_PATH}
        if len(expressions) > 1:
            entry["name"] = f"scheduled-{i + 1}"
        crons.append(entry)
        done.added.append(f"crons {entry['cron']} → POST {SCHEDULED_PATH} (from triggers.crons)")

    if bindings:
        done.config["bindings"] = bindings
    if env:
        done.config["env"] = env
    if crons:
        done.config["crons"] = crons
    done.left = left_in(wrangler, file)
    return done


def left_in(wrangler: Dict[str, Any], file: str) -> List[Tuple[str, str]]:
    """What a wrangler config still names that NoClick's build refuses, each with what the code does instead."""
    left: List[Tuple[str, str]] = []
    for key, kind, sdk in (("d1_databases", "database", "database"), ("kv_namespaces", "dict", "dict"),
                           ("r2_buckets", "bucket", "bucket")):
        for entry in _entries(wrangler.get(key)):
            name = entry.get("binding")
            if name:
                left.append((key, f"read env.{name} with Project.current().{sdk}(\"{name}\") (NoClick's SDK; "
                                  f"the {kind} is bound to the app as {name})"))
    queues = wrangler.get("queues")
    if isinstance(queues, dict) and (queues.get("producers") or queues.get("consumers")):
        left.append(("queues", "send with Project.current().queue(\"NAME\").put(...) and read the queue from the "
                               "app's own code; NoClick doesn't run a Worker's queue() handler"))
    triggers = wrangler.get("triggers")
    if isinstance(triggers, dict) and triggers.get("crons"):
        left.append(("triggers", f"answer POST {SCHEDULED_PATH} in the worker's fetch handler: NoClick calls that "
                                 "path on each tick and never a scheduled() handler (check the request with "
                                 "Project.current().verify_request)"))
    return left


def clip(text: str, limit: int = 60) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def write_config(root: Path, data: Dict[str, Any]) -> None:
    (root / NOCLICK_JSON).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


# --- editing a wrangler config as written ---------------------------------------------------------------------


def set_top_level(text: str, key: str, value: Any) -> str:
    """``text`` (JSON or JSONC) with its top-level ``key`` set to ``value``, comments and everything else as written."""
    spans = _top_level(text)
    indent = _indent(text)
    rendered = json.dumps(value, indent=len(indent.expandtabs(2)) or 2).replace("\n", "\n" + indent)
    if key in spans:
        start, end = spans[key]
        return text[:start] + rendered + text[end:]
    close = spans["}"][0]
    if _last_code(text, close) not in ("{", ","):
        end = _end_of_value(text, close)
        text, close = text[:end] + "," + text[end:], close + 1
    at = len(text[:close].rstrip())
    return text[:at] + f"\n{indent}{json.dumps(key)}: {rendered}\n" + text[close:]


def _skip(text: str, i: int) -> int:
    """Past whitespace and comments from ``i``."""
    while i < len(text):
        if text[i].isspace():
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = len(text) if end < 0 else end + 2
        else:
            break
    return i


def _string_end(text: str, i: int) -> int:
    j = i + 1
    while j < len(text) and text[j] != '"':
        j += 2 if text[j] == "\\" else 1
    return j + 1


def _value_end(text: str, i: int) -> int:
    """Where the JSON value starting at ``i`` ends."""
    if text[i] == '"':
        return _string_end(text, i)
    if text[i] in "{[":
        depth, j = 0, i
        while j < len(text):
            j = _skip(text, j)
            c = text[j]
            if c == '"':
                j = _string_end(text, j)
                continue
            if c in "{[":
                depth += 1
            elif c in "}]":
                depth -= 1
                if depth == 0:
                    return j + 1
            j += 1
        raise ValueError("unbalanced")
    j = i
    while j < len(text) and text[j] not in ",}] \t\r\n/":
        j += 1
    return j


def _top_level(text: str) -> Dict[str, Tuple[int, int]]:
    """Each top-level key's value span, and the root's closing brace (``"}"``)."""
    i = _skip(text, 0)
    if i >= len(text) or text[i] != "{":
        raise ValueError("not an object")
    spans: Dict[str, Tuple[int, int]] = {}
    i = _skip(text, i + 1)
    while i < len(text) and text[i] != "}":
        end = _string_end(text, i)
        key = json.loads(text[i:end])
        i = _skip(text, end)
        i = _skip(text, i + 1)  # past ':'
        value_end = _value_end(text, i)
        spans[key] = (i, value_end)
        i = _skip(text, value_end)
        if i < len(text) and text[i] == ",":
            i = _skip(text, i + 1)
    spans["}"] = (i, i + 1)
    return spans


def _last_code(text: str, before: int) -> str:
    """The last character before ``before`` that isn't whitespace or a comment."""
    i, last = _skip(text, 0), ""
    while i < before:
        if text[i] == '"':
            i = _string_end(text, i)
            last = '"'
        else:
            last = text[i]
            i += 1
        i = _skip(text, i)
    return last


def _end_of_value(text: str, before: int) -> int:
    i, end = _skip(text, 0), 0
    while i < before:
        if text[i] == '"':
            i = _string_end(text, i)
        else:
            i += 1
        end = i
        i = _skip(text, i)
    return end


def _indent(text: str) -> str:
    found = re.search(r"\n([ \t]+)\"", text)
    return found.group(1) if found else "  "


# --- applying ----------------------------------------------------------------------------------------------------


@dataclass
class Applied:
    """What applying ``noclick.json`` changed on the app, each in words (``changes``), and the resources it made."""

    changes: List[str] = field(default_factory=list)
    made: List[str] = field(default_factory=list)


def apply(project: Any, config: AppConfig, *, classes: Dict[str, Callable[..., Any]]) -> Applied:
    """Give ``project`` what ``config`` asks for, changing only what differs. ``classes`` maps each binding kind to
    the SDK class that finds or makes it (``Database``, ``Bucket``, ``Dict``, ``Queue``)."""
    from ..exceptions import NotFound

    done = Applied()
    if config.bindings:
        bound = {b.name: b for b in project.bindings()}
        for spec in config.bindings:
            have = bound.get(spec.name)
            if have is not None and have.kind == spec.kind and have.resource_name == spec.resource:
                continue
            cls = classes[spec.kind]
            resource = cls.from_name(spec.resource)
            try:
                resource.id  # loads it: is there one by that name?
            except NotFound:
                region = getattr(project, "region", None)
                resource = cls.from_name(spec.resource, create_if_missing=True, **dict(spec.options),
                                         **({"region": region} if region else {}))
                done.made.append(f"{spec.kind} {spec.resource}")
            project.bind(spec.name, resource)
            was = f" (was {have.kind} {have.resource_name})" if have is not None else ""
            done.changes.append(f"bound {spec.name} to the {spec.kind} {spec.resource}{was}")
    if config.env:
        settings = project.settings.list()
        for name, value in config.env.items():
            if settings.get(name) == value:
                continue
            project.settings.set(name, value)
            done.changes.append(f"set {name} = {clip(value)}")
    if config.crons:
        from ..cron import Cron

        schedules = {s.name: s for s in project.schedules()}
        for spec in config.crons:
            have = schedules.get(spec.key)
            if have is not None and (have.cron, have.path, have.tz) == (spec.cron, spec.path, spec.tz):
                continue
            project.schedule(Cron(spec.cron, tz=spec.tz), path=spec.path, name=spec.name)
            done.changes.append(f"{'changed' if have is not None else 'added'} the schedule {spec.said()}")
    return done
