"""Generate the Python SDK's reference, the JSON the docs at noclick.com/docs render.

    python scripts/gen_reference.py                        # print the reference JSON
    python scripts/gen_reference.py --out reference.json   # write it to a file
    python scripts/gen_reference.py --check --out FILE     # exit 1 when FILE is out of date
    python scripts/gen_reference.py --surface              # print the public names and their members

Reads the package with ``ast`` (nothing is imported), so the reference is
exactly what the code declares: ``__all__``, signatures, docstrings and
attribute comments. Docstrings are written in RST-lite (````code````, ``::``
literal blocks); they come out as Markdown.
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "noclick"
DISTRIBUTION = "noclick"

# One page per module; private modules land on the page of the name they define.
PAGE_OF_MODULE = {
    "_client": "Client", "_version": "Client", "_object": "Page", "_scope": "as_user", "_usage": "usage",
    "agent": "Agent", "api_request": "ApiRequest", "approval": "Approval", "brand": "Brand", "channel": "Channel",
    "connection": "Connection", "exceptions": "Error", "human": "Human", "inbox": "Inbox",
    "operation": "Operation", "phone_number": "PhoneNumber", "policy": "Policy",
    "sandbox": "Sandbox", "session": "Session", "tool_call": "ToolCall", "toolkit": "Toolkit", "user": "User",
    # Designed, not built yet (``@designed`` in the package).
    "agent_extras": "Agent", "agent_conversations": "Agent", "ai": "AI", "app_services": "Project", "browser": "Browser", "bucket": "Bucket",
    "card": "Card", "cron": "Triggers", "database": "Database", "domain": "Domain", "export": "ExportBundle",
    "mcp_server": "McpServer", "project": "Project", "repo": "Repo", "trigger": "Triggers", "webhook": "Webhook",
    "workflow": "Workflow", "volume": "Volume", "dicts": "Dict", "queues": "Queue", "secret": "Secret",
    "coordination": "Agent", "workspace": "Channel", "machine": "Machine",
    "region": "Region", "_attachment": "Agent", "_feedback": "feedback", "trash": "TrashItem", "versions": "Secret",
    "memory": "Memory", "terminal": "Agent", "live": "Project", "skill": "Skill", "compute": "compute",
    "agent_move": "AgentMove", "estimate": "estimate", "workflow_resources": "Workflow", "_watch": "watch",
    "step_type": "Workflow", "notifications": "Notifications", "key": "Key",
    "workflow_approval": "Workflow", "workflow_example": "Workflow",
}
# Module docstrings that describe internals rather than the page's names.
NO_INTRO = {"_object", "_client", "_version", "_attachment", "agent_extras", "agent_conversations", "app_services", "cron", "live",
            "workflow_resources", "step_type", "workflow_example"}

# The index page's sections, like the reference's table of contents.
GROUPS: List[Tuple[str, List[str]]] = [
    ("Configuration", ["Client", "configure", "default_client", "Page", "Key", "regions", "Region"]),
    ("Your users", ["User", "Spending", "as_user", "Session", "Brand"]),
    ("Their accounts", ["Connection", "run", "ConnectLink", "IntegrationInfo", "IntegrationOperation", "IntegrationEvent"]),
    ("Hosted agents", ["Agent", "HarnessInfo", "ModelUsage", "AgentGrant", "Cron", "OnWebhook", "OnEvent", "OnPlatformEvent", "OnQueue", "AgentTrigger", "AgentMemory", "Memory", "Skill",
                       "AgentWorkspace", "ShareLink", "Wakeup", "Job", "Before", "Every", "Agents", "Platform", "Attachment",
                       "Terminal", "AgentMove",
                       "Channel", "Subscription",
                       "Workspace", "A2AMember"]),
    ("Tools for your own LLM", ["Toolkit", "ToolResult", "McpServer", "AI"]),
    ("People in the loop", ["Human", "HumanOperations", "HumanRequest", "Approval", "Policy"]),
    ("Acting in the world", ["Inbox", "PhoneNumber", "Browser", "BrowserProfile", "BrowserLogin", "Card", "Sandbox",
                             "Machine", "compute"]),
    ("Build and host", ["Project", "Deployment", "Schedule", "ProjectEmail", "ProjectPayments", "ProjectSignIn", "ProjectAI", "ProjectLive", "Repo",
                        "Domain", "DomainPurchase", "Workflow", "estimate", "Estimate"]),
    ("Data", ["Database", "Bucket", "Volume", "Dict", "Queue", "Secret"]),
    ("In production", ["Operation", "TrashItem", "Event", "Webhook", "watch", "ToolCall", "ApiRequest", "usage", "Usage",
                       "Notifications", "ExportBundle", "feedback"]),
    ("Errors", ["Error", "NeedsConnection", "CredentialDisconnected", "ApprovalRequired", "SpendCapExceeded", "SpendingPaused",
                "Conflict",
                "WebhookSignatureError"]),
]

# Parameters most methods take, described once.
COMMON_PARAMS = {
    "client": "The client to send with; defaults to the module client built from `NOCLICK_API_KEY`.",
    "user": "Who the call acts for. Defaults to the user set by `noclick.as_user` (none: the account itself).",
    "user_filter": (
        "Which users a read covers: `noclick.ALL_USERS`, `noclick.NO_USER`, a `User`, or your id for one. "
        "It filters without acting as that user."
    ),
    "cursor": "The `next_cursor` of the page before; omit it for the first page.",
    "limit": "Return at most this many.",
    "idempotency_key": "Makes a retried create safe: the same key returns the first result. Generated when omitted.",
}
# Sentinel defaults and what they mean.
SENTINELS = {
    "AMBIENT": "the current user",
    "UNSET": "unchanged",
}
# Dataclasses you build yourself (the rest only come back from calls).
CONSTRUCTIBLE = {"A2AMember", "Cron", "OnWebhook", "OnEvent", "OnPlatformEvent", "DomainContact", "Before", "Every", "Agents", "Platform"}
# Classes whose constructor is internal (reached another way: ``sb.files``, a raise).
NO_CONSTRUCTOR = {"SandboxFiles", "MachineFiles", "Error"}
CONSTANT_DOCS = {"__version__": "This client's version."}


# --- docstrings -----------------------------------------------------------

_INLINE = re.compile(r"``(.+?)``", re.S)


def raw_doc(node: ast.AST) -> Optional[str]:
    """A docstring dedented by its own statement's indentation (not by the
    smallest indent, which would flatten a docstring that is all example)."""
    body = getattr(node, "body", None)
    if not body:
        return None
    first = body[0]
    if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str)):
        return None
    indent = first.col_offset
    lines = first.value.value.expandtabs().split("\n")
    out = [lines[0].strip()]
    for line in lines[1:]:
        out.append(line[indent:] if not line[:indent].strip() else line.lstrip())
    return "\n".join(out).strip("\n")


def to_markdown(doc: Optional[str]) -> str:
    """RST-lite to Markdown: ````x```` to `x`, ``::`` and indented blocks to fenced Python."""
    if not doc:
        return ""
    lines = doc.split("\n")
    blocks: List[Tuple[str, List[str]]] = []
    paragraph: List[str] = []
    literal = False  # the line before ended with "::"

    def flush() -> None:
        if paragraph:
            blocks.append(("p", paragraph[:]))
            paragraph.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            flush()
            i += 1
            continue
        if line[:1] in (" ", "\t") and (literal or not paragraph):
            flush()
            block: List[str] = []
            while i < len(lines) and (not lines[i].strip() or lines[i][:1] in (" ", "\t")):
                block.append(lines[i])
                i += 1
            while block and not block[-1].strip():
                block.pop()
            blocks.append(("code", _dedent(block)))
            literal = False
            continue
        paragraph.append(line.strip())
        literal = line.rstrip().endswith("::")
        i += 1
    flush()
    out: List[str] = []
    for kind, content in blocks:
        if kind == "code":
            out.append("```python\n" + "\n".join(content) + "\n```")
            continue
        text = "\n".join(content)
        if text.endswith("::"):
            text = text[:-2].rstrip()
            text = f"{text}:" if text else ""
        text = _INLINE.sub(lambda m: "`" + " ".join(m.group(1).split()) + "`", text)
        if text:
            out.append(text)
    return "\n\n".join(out)


_SECTION = re.compile(r"^(Returns|Usage):(:?)\s*$")


def split_sections(doc: Optional[str]) -> Tuple[str, str, str]:
    """A docstring's body, and its ``Returns:`` and ``Usage:`` sections as Markdown.
    A section runs from its column-0 header to the next one; ``Usage::`` is all code,
    ``Usage:`` is prose with ``::`` examples."""
    if not doc:
        return "", "", ""
    body: List[str] = []
    found: Dict[str, Tuple[bool, List[str]]] = {}
    current: Optional[List[str]] = body
    for line in doc.split("\n"):
        match = _SECTION.match(line)
        if match:
            name = match.group(1)
            if name in found:
                raise SystemExit(f"two {name}: sections in one docstring:\n{doc}")
            found[name] = (bool(match.group(2)), [])
            current = found[name][1]
            continue
        current.append(line)

    def section(name: str) -> str:
        literal, lines = found.get(name, (False, []))
        lines = _dedent(lines)
        while lines and not lines[-1].strip():
            lines.pop()
        while lines and not lines[0].strip():
            lines.pop(0)
        if not lines:
            return ""
        return "```python\n" + "\n".join(lines) + "\n```" if literal else to_markdown("\n".join(lines))

    return to_markdown("\n".join(body).strip("\n")), section("Returns"), section("Usage")


def doc_fields(node: ast.AST) -> Dict[str, str]:
    body, returns_doc, usage = split_sections(raw_doc(node))
    return {"doc": body, "returns_doc": returns_doc, "usage": usage}


def _dedent(block: List[str]) -> List[str]:
    widths = [len(line) - len(line.lstrip()) for line in block if line.strip()]
    cut = min(widths) if widths else 0
    return [line[cut:] if line.strip() else "" for line in block]


_ABBREVIATIONS = ("e.g", "i.e", "etc", "vs")


def first_sentence(markdown: str) -> str:
    """The summary line for index tables: the first sentence of the first paragraph."""
    paragraph = markdown.split("\n\n", 1)[0].replace("\n", " ").strip()
    if paragraph.startswith("```"):
        return ""
    code = False
    for i, ch in enumerate(paragraph):
        if ch == "`":
            code = not code
        elif ch == "." and not code and (i + 1 == len(paragraph) or paragraph[i + 1] == " "):
            if paragraph[:i].lower().endswith(_ABBREVIATIONS):
                continue
            return paragraph[: i + 1]
    return paragraph


# --- annotations and signatures ------------------------------------------

_BUILTIN_GENERICS = {"List": "list", "Dict": "dict", "Tuple": "tuple", "Type": "type", "FrozenSet": "frozenset", "Set": "set"}


def annotation(node: Optional[ast.expr]) -> Optional[str]:
    """``Optional[str]`` -> ``str | None``, ``List[X]`` -> ``list[X]``, forward refs unquoted."""
    if node is None:
        return None
    return _ann(node)


def _ann(node: ast.expr) -> str:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            try:
                return _ann(ast.parse(node.value, mode="eval").body)
            except SyntaxError:
                return node.value
        return repr(node.value)
    if isinstance(node, ast.Name):
        return node.id  # a bare name is a class (``Dict`` is noclick's); typing's generics are always subscripted
    if isinstance(node, ast.Attribute):
        return ast.unparse(node)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return f"{_ann(node.left)} | {_ann(node.right)}"
    if isinstance(node, ast.Subscript):
        base = node.value
        inner = node.slice
        items = list(inner.elts) if isinstance(inner, ast.Tuple) else [inner]
        name = base.id if isinstance(base, ast.Name) else ast.unparse(base)
        if name == "Optional":
            return f"{_ann(items[0])} | None"
        if name == "Union":
            parts = [_ann(i) for i in items]
            if "None" in parts:  # keep None last
                parts = [p for p in parts if p != "None"] + ["None"]
            return " | ".join(parts)
        if name == "Literal":
            return f"Literal[{', '.join(ast.unparse(i) for i in items)}]"
        return f"{_BUILTIN_GENERICS.get(name, name)}[{', '.join(_ann(i) for i in items)}]"
    if isinstance(node, ast.List):
        return f"[{', '.join(_ann(i) for i in node.elts)}]"
    return ast.unparse(node)


def default_text(node: Optional[ast.expr], constants: Optional[Dict[str, str]] = None) -> Optional[str]:
    if node is None:
        return None
    if isinstance(node, ast.Name) and node.id in SENTINELS:
        return "..."
    if isinstance(node, ast.Name) and constants and node.id.startswith("_") and node.id in constants:
        return constants[node.id]
    return ast.unparse(node)


def default_note(node: Optional[ast.expr]) -> Optional[str]:
    if isinstance(node, ast.Name) and node.id in SENTINELS:
        return SENTINELS[node.id]
    return None


def params_of(fn: ast.FunctionDef | ast.AsyncFunctionDef, *, drop_first: bool,
              constants: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    args = fn.args
    positional = list(args.posonlyargs) + list(args.args)
    if drop_first and positional:
        positional = positional[1:]
    pos_defaults = [None] * (len(list(args.posonlyargs) + list(args.args)) - len(args.defaults)) + list(args.defaults)
    if drop_first and pos_defaults:
        pos_defaults = pos_defaults[1:]
    out: List[Dict[str, Any]] = []
    for arg, default in zip(positional, pos_defaults):
        out.append(_param(arg, default, "positional", constants))
    if args.vararg:
        out.append(_param(args.vararg, None, "var_positional", constants))
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        out.append(_param(arg, default, "keyword", constants))
    if args.kwarg:
        out.append(_param(args.kwarg, None, "var_keyword", constants))
    return out


def _param(arg: ast.arg, default: Optional[ast.expr], kind: str, constants: Optional[Dict[str, str]]) -> Dict[str, Any]:
    required = default is None and kind in ("positional", "keyword")
    return {
        "name": arg.arg,
        "kind": kind,
        "type": annotation(arg.annotation),
        "default": default_text(default, constants),
        "default_note": default_note(default),
        "required": required,
        "doc": COMMON_PARAMS.get(arg.arg),
    }


def signature(call: str, params: List[Dict[str, Any]], returns: Optional[str]) -> str:
    """``Agent.create(name, *, instructions, model=None) -> Agent``, wrapped like Black past 88 columns."""
    parts: List[str] = []
    star_done = False
    for p in params:
        if p["kind"] == "var_positional":
            parts.append(f"*{p['name']}")
            star_done = True
            continue
        if p["kind"] == "var_keyword":
            parts.append(f"**{p['name']}")
            continue
        if p["kind"] == "keyword" and not star_done:
            parts.append("*")
            star_done = True
        parts.append(p["name"] if p["default"] is None else f"{p['name']}={p['default']}")
    tail = f" -> {returns}" if returns else ""
    one_line = f"{call}({', '.join(parts)}){tail}"
    if len(one_line) <= 88:
        return one_line
    lines, current = [], ""
    for part in parts:
        piece = f"{part}, "
        if current and len("    " + current + piece) > 88:
            lines.append("    " + current.rstrip())
            current = ""
        current += piece
    if current:
        lines.append("    " + current.rstrip().rstrip(","))
    return f"{call}(\n" + "\n".join(lines) + f"\n){tail}"


# --- modules ---------------------------------------------------------------


class Module:
    def __init__(self, name: str) -> None:
        self.name = name
        self.path = PACKAGE / f"{name}.py"
        self.source = self.path.read_text()
        self.lines = self.source.split("\n")
        self.tree = ast.parse(self.source)
        self.doc = raw_doc(self.tree)
        self.defs: Dict[str, ast.AST] = {}
        self.constants: Dict[str, str] = {}
        for node in self.tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.constants[target.id] = ast.unparse(node.value)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                self.defs[node.name] = node
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.defs[target.id] = node
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                self.defs[node.target.id] = node

    def comment_above(self, node: ast.AST) -> Optional[str]:
        """The ``#`` / ``#:`` comment lines right above a statement, joined."""
        found: List[str] = []
        line = node.lineno - 2
        while line >= 0 and re.match(r"^[A-Z_][A-Z0-9_]* = ", self.lines[line]):
            line -= 1  # one comment over a run of constants covers each
        while line >= 0 and self.lines[line].strip().startswith("#"):
            text = self.lines[line].strip().lstrip("#").lstrip(":").strip()
            if text.startswith("---"):
                break
            found.append(text)
            line -= 1
        if not found:
            return None
        return to_markdown(" ".join(reversed(found)))


def decorator_names(node: ast.AST) -> List[str]:
    names = []
    for d in getattr(node, "decorator_list", []):
        target = d.func if isinstance(d, ast.Call) else d
        names.append(target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", ""))
    return names


def designed_param_names(fn: ast.FunctionDef | ast.AsyncFunctionDef, params: List[Dict[str, Any]]) -> set:
    """The names ``@designed_params(...)`` lists; each must be one of the call's parameters."""
    names = {arg.value for d in fn.decorator_list
             if isinstance(d, ast.Call) and getattr(d.func, "id", getattr(d.func, "attr", "")) == "designed_params"
             for arg in d.args if isinstance(arg, ast.Constant)}
    unknown = names - {p["name"] for p in params}
    if unknown:
        raise SystemExit(f"{fn.name}: @designed_params names {sorted(unknown)}, which it doesn't take")
    return names


def has_yield(fn: ast.AST) -> bool:
    return any(isinstance(n, (ast.Yield, ast.YieldFrom)) for n in ast.walk(fn))


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


INSTANCE_NAMES = {"PhoneNumber": "number", "InboxMessage": "message", "SandboxFiles": "sb.files", "HumanRequest": "request",
                  "MachineFiles": "machine.files",
                  "ConnectLink": "link", "Toolkit": "toolkit",
                  # Designed: the names the guide's examples use.
                  "Database": "db", "Project": "app", "ProjectEmail": "app.email", "ProjectPayments": "app.payments",
                  "ProjectSignIn": "app.sign_in", "ProjectSecrets": "app.secrets", "ProjectAI": "app.ai", "BrowserProfile": "profile",
                  "Webhook": "hook", "McpServer": "server", "AgentMemory": "agent.memory", "AgentWorkspace": "workspace", "Workspace": "ws",
                  "ShareLink": "link", "DomainDns": "domain.dns", "DomainPurchase": "purchase",
                  "Dict": "d", "QueueMessage": "msg", "Queue": "queue", "Volume": "vol"}


def instance_name(cls: str) -> str:
    return INSTANCE_NAMES.get(cls, snake(cls))


def method_entry(mod: Module, cls: Optional[str], fn: ast.FunctionDef | ast.AsyncFunctionDef) -> Dict[str, Any]:
    decorators = decorator_names(fn)
    is_class = "classmethod" in decorators
    is_static = "staticmethod" in decorators
    constructor = fn.name == "__init__"
    iterator = isinstance(fn, ast.AsyncFunctionDef) and has_yield(fn)
    params = params_of(fn, drop_first=bool(cls) and not is_static, constants=mod.constants)
    for name in designed_param_names(fn, params):
        next(p for p in params if p["name"] == name)["designed"] = True
    returns = annotation(fn.returns)
    if constructor:
        returns = None
    if iterator and returns:
        returns = re.sub(r"^AsyncIterator\[", "Iterator[", returns)
    if fn.name == "__getitem__":
        name = "__getitem__"
        call = f"{instance_name(cls)}[{params[0]['name']}]" if cls else fn.name
        sig = f"{call} -> {returns}" if returns else call
    else:
        name = fn.name
        if constructor:
            call = f"noclick.{cls}"
        elif cls is None:
            call = f"noclick.{fn.name}"
        elif is_class or is_static:
            call = f"noclick.{cls}.{fn.name}"
        else:
            call = f"{instance_name(cls)}.{fn.name}"
        sig = signature(call, params, returns)
    return {
        "kind": "constructor" if constructor else ("classmethod" if is_class else "staticmethod" if is_static else "method"),
        "name": name,
        "signature": sig,
        "params": params,
        "returns": returns,
        "aio": "synced" in decorators,
        "iterator": iterator,
        "designed": "designed" in decorators,
        **doc_fields(fn),
    }


def is_public(name: str) -> bool:
    return not name.startswith("_")


def class_entry(mod: Module, node: ast.ClassDef, public: set) -> Dict[str, Any]:
    decorators = decorator_names(node)
    bases = [annotation(b) for b in node.bases]
    shown_bases = [b for b in bases if b and not b.startswith("_") and not b.startswith("Generic")]
    attributes: List[Dict[str, Any]] = []
    methods: List[Dict[str, Any]] = []
    error_type = http_status = None
    context_manager = False
    dataclass = "dataclass" in decorators
    for item in node.body:
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            name = item.target.id
            if not is_public(name):
                continue
            doc = None
            value = item.value
            if isinstance(value, ast.Call) and getattr(value.func, "id", "") in ("field", "_detail"):
                doc = next((to_markdown(k.value.value) for k in value.keywords
                            if k.arg == "doc" and isinstance(k.value, ast.Constant)), None)
            doc = doc or mod.comment_above(item)
            if name == "raw" and not doc:
                doc = "The response JSON exactly as the API sent it."
            default = None
            if dataclass and value is not None:
                if not isinstance(value, ast.Call):
                    default = ast.unparse(value)
                else:
                    for k in value.keywords:
                        if k.arg == "default":
                            default = ast.unparse(k.value)
                        elif k.arg == "default_factory":
                            default = f"{ast.unparse(k.value)}()"
            attributes.append({"name": name, "type": annotation(item.annotation), "doc": doc, "default": default})
        elif isinstance(item, ast.Assign):
            names = [t.id for t in item.targets if isinstance(t, ast.Name)]
            tuple_targets = [t for t in item.targets if isinstance(t, ast.Tuple)]
            if tuple_targets and isinstance(item.value, ast.Tuple):
                for target, value in zip(tuple_targets[0].elts, item.value.elts):
                    if isinstance(target, ast.Name) and target.id == "type" and isinstance(value, ast.Constant):
                        error_type = value.value
                    if isinstance(target, ast.Name) and target.id == "http_status" and isinstance(value, ast.Constant):
                        http_status = value.value
            for name in names:
                if name == "type" and isinstance(item.value, ast.Constant):
                    error_type = item.value.value
                if name == "http_status" and isinstance(item.value, ast.Constant):
                    http_status = item.value.value
        elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            item_decorators = decorator_names(item)
            if item.name in ("__enter__", "__aenter__"):
                context_manager = True
            if "overload" in item_decorators or "setter" in item_decorators:  # a setter is its property's
                continue
            if "property" in item_decorators:
                if is_public(item.name):
                    attributes.append({
                        "name": item.name, "type": annotation(item.returns),
                        "doc": to_markdown(raw_doc(item)) or None, "default": None,
                        **({"designed": True} if "designed" in item_decorators else {}),
                    })
                continue
            if item.name == "__init__":
                attributes += _init_attributes(item)
                if node.name not in NO_CONSTRUCTOR:
                    methods.insert(0, method_entry(mod, node.name, item))
                continue
            if item.name == "__getitem__" and raw_doc(item):
                methods.append(method_entry(mod, node.name, item))
                continue
            if is_public(item.name):
                methods.append(method_entry(mod, node.name, item))
    if dataclass and node.name in CONSTRUCTIBLE:
        fields = [a for a in attributes if a["name"] != "raw"]
        params = [{
            "name": a["name"], "kind": "positional", "type": a["type"], "default": a["default"],
            "default_note": None, "required": a["default"] is None, "doc": a["doc"],
        } for a in fields]
        methods.insert(0, {
            "kind": "constructor", "name": "__init__", "signature": signature(f"noclick.{node.name}", params, None),
            "params": params, "returns": None, "aio": False, "iterator": False, "designed": "designed" in decorators,
            "doc": "", "returns_doc": "", "usage": "",
        })
    entry: Dict[str, Any] = {
        "kind": "exception" if error_type is not None or node.name in ("Error",) or _is_error(bases) else "class",
        "name": node.name,
        "signature": f"class {node.name}" + (f"({', '.join(shown_bases)})" if shown_bases else ""),
        "bases": shown_bases,
        "dataclass": dataclass,
        "context_manager": context_manager,
        "live_object": "_Object" in bases,
        "designed": "designed" in decorators,
        **doc_fields(node),
        "attributes": attributes,
        "methods": methods,
    }
    if entry["kind"] == "exception":
        entry["error_type"] = error_type
        entry["http_status"] = http_status
    return entry


def _is_error(bases: List[Optional[str]]) -> bool:
    return any(b and (b == "Error" or b.endswith("Error") or b == "Exception") for b in bases)


def _init_attributes(fn: ast.FunctionDef) -> List[Dict[str, Any]]:
    """``self.x = x`` assignments in ``__init__``: public instance attributes."""
    types = {a.arg: annotation(a.annotation) for a in fn.args.args + fn.args.kwonlyargs}
    found: List[Dict[str, Any]] = []
    seen = set()
    for stmt in ast.walk(fn):
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target] if isinstance(stmt, ast.AnnAssign) else []
        for target in targets:
            if (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                    and target.value.id == "self" and is_public(target.attr) and target.attr not in seen):
                seen.add(target.attr)
                value = getattr(stmt, "value", None)
                kind = types.get(value.id) if isinstance(value, ast.Name) else None
                if isinstance(stmt, ast.AnnAssign):
                    kind = annotation(stmt.annotation)
                found.append({"name": target.attr, "type": kind, "doc": None, "default": None})
    return found


def function_entry(mod: Module, node: ast.FunctionDef | ast.AsyncFunctionDef) -> Dict[str, Any]:
    entry = method_entry(mod, None, node)
    entry["kind"] = "function"
    return entry


def constant_entry(mod: Module, name: str, node: ast.AST) -> Dict[str, Any]:
    value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
    if isinstance(value, ast.Name) and value.id in mod.defs and isinstance(mod.defs[value.id], ast.ClassDef):
        return {"kind": "alias", "name": name, "target": value.id, "doc": f"Another name for `{value.id}`."}
    return {
        "kind": "constant",
        "name": name,
        "signature": f"noclick.{name} = {ast.unparse(value)}" if value is not None else f"noclick.{name}",
        "doc": mod.comment_above(node) or CONSTANT_DOCS.get(name, ""),
    }


# --- assembly ---------------------------------------------------------------


def public_api() -> Tuple[str, List[str], Dict[str, Tuple[str, str]]]:
    init = ast.parse((PACKAGE / "__init__.py").read_text())
    names: List[str] = []
    origin: Dict[str, Tuple[str, str]] = {}
    for node in init.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            names = [ast.literal_eval(e) for e in node.value.elts]
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            for alias in node.names:
                origin[alias.asname or alias.name] = (node.module, alias.name)
    return raw_doc(init) or "", names, origin


def build() -> Dict[str, Any]:
    package_doc, names, origin = public_api()
    missing = [n for n in names if n not in origin]
    if missing:
        raise SystemExit(f"__all__ names without a relative import: {missing}")
    unmapped = sorted({origin[n][0] for n in names} - PAGE_OF_MODULE.keys())
    if unmapped:
        raise SystemExit(f"Modules with no reference page: {unmapped} (add them to PAGE_OF_MODULE)")
    modules = {m: Module(m) for m in sorted({origin[n][0] for n in names})}
    public = set(names)
    pages: Dict[str, Dict[str, Any]] = {}
    symbols: Dict[str, str] = {}
    for name in names:
        module_name, real = origin[name]
        mod = modules[module_name]
        node = mod.defs.get(real)
        if node is None:
            raise SystemExit(f"{name}: no definition of {real} in {module_name}.py")
        if isinstance(node, ast.ClassDef):
            entry = class_entry(mod, node, public)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            entry = function_entry(mod, node)
        else:
            entry = constant_entry(mod, name, node)
        entry["name"] = name
        entry["summary"] = first_sentence(entry.get("doc") or "")
        slug = PAGE_OF_MODULE[module_name]
        page = pages.setdefault(slug, {
            "slug": slug, "title": slug, "module": module_name, "intro": "", "items": [],
        })
        if module_name not in NO_INTRO and mod.doc and not page["intro"]:
            page["intro"] = to_markdown(mod.doc)
        page["items"].append(entry)
        symbols[name] = f"{slug}#{name}"
        for method in entry.get("methods", []):
            if method["kind"] != "constructor" and method["name"] != "__getitem__":
                symbols[f"{name}.{method['name']}"] = f"{slug}#{name}.{method['name']}"
        for attribute in entry.get("attributes", []):
            symbols.setdefault(f"{name}.{attribute['name']}", f"{slug}#{name}")
    _add_instance_symbols(pages, symbols)
    live = {e["name"] for p in pages.values() for e in p["items"] if e.get("live_object")}
    for page in pages.values():
        for e in page["items"]:
            if e.get("bases") and any(b in live for b in e["bases"]):
                e["live_object"] = True
    # The page's own name leads it.
    for page in pages.values():
        page["items"].sort(key=lambda e: 0 if e["name"] == page["slug"] else 2 if e["kind"] in ("constant", "alias") else 1)
    ordered = sorted(pages.values(), key=lambda p: (p["slug"][0].islower(), p["slug"].lower()))
    by_name = {e["name"]: e for p in ordered for e in p["items"]}
    groups = []
    for title, members in GROUPS:
        entries = []
        for member in members:
            if member not in by_name:
                raise SystemExit(f"GROUPS names {member}, which isn't public")
            entry = by_name[member]
            summary = entry["summary"] or (
                f"Raised for `{entry['error_type']}` ({entry['http_status']})." if entry.get("error_type") else ""
            )
            entries.append({"name": member, "href": symbols[member], "summary": summary, "designed": bool(entry.get("designed"))})
        groups.append({"title": title, "entries": entries})
    common = _common_members()
    return {
        "package": "noclick",
        "distribution": DISTRIBUTION,
        "version": _version(),
        "intro": to_markdown(package_doc),
        "objects": common,
        "groups": groups,
        "pages": ordered,
        "symbols": symbols,
    }


def _add_instance_symbols(pages: Dict[str, Dict[str, Any]], symbols: Dict[str, str]) -> None:
    """``agent.message`` -> ``Agent.message``: the names the signatures call instances by.
    A name two classes would claim links nowhere."""
    claims: Dict[str, set] = {}
    for page in pages.values():
        for entry in page["items"]:
            if entry["kind"] not in ("class", "exception"):
                continue
            prefix = instance_name(entry["name"])
            for method in entry["methods"]:
                if method["kind"] == "method" and method["name"] != "__getitem__":
                    claims.setdefault(f"{prefix}.{method['name']}", set()).add(f"{page['slug']}#{entry['name']}.{method['name']}")
            for attribute in entry["attributes"]:
                claims.setdefault(f"{prefix}.{attribute['name']}", set()).add(f"{page['slug']}#{entry['name']}")
    for key, targets in claims.items():
        if len(targets) == 1 and key not in symbols:
            symbols[key] = next(iter(targets))


def _common_members() -> Dict[str, Any]:
    """What every live object (``User``, ``Agent``, ...) has, from the private base."""
    mod = Module("_object")
    base = mod.defs["_Object"]
    entry = class_entry(mod, base, set())
    methods = []
    for m in entry["methods"]:
        if m["kind"] == "method":
            methods.append({**m, "signature": m["signature"].replace("__object.", "obj.").replace("-> T", "-> Self"),
                            "returns": "Self"})
    return {"doc": to_markdown(mod.doc), "attributes": entry["attributes"], "methods": methods}


def _version() -> str:
    tree = ast.parse((PACKAGE / "_version.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            return node.value.value
    return ""


def render(data: Dict[str, Any]) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def surface(data: Dict[str, Any]) -> Dict[str, Any]:
    """The public names and each one's members and bases, which the TypeScript client's parity test compares with
    its own: a live object's include what every live object has, and a class's those of its private bases, whose
    public bases count as its own."""
    _, _, origin = public_api()
    common = {m["name"] for m in data["objects"]["methods"] + data["objects"]["attributes"]}
    modules: Dict[str, Module] = {}

    def private_bases(module: str, node: ast.ClassDef) -> Tuple[set, set]:
        mod = modules.setdefault(module, Module(module))
        members: set = set()
        bases: set = set()
        for base in node.bases:
            name = annotation(base) or ""
            if name.startswith("_") and isinstance(mod.defs.get(name), ast.ClassDef):
                entry = class_entry(mod, mod.defs[name], set())
                inner_members, inner_bases = private_bases(module, mod.defs[name])
                members |= {m["name"] for m in entry["methods"] + entry["attributes"]} | inner_members
                bases |= set(entry["bases"]) | inner_bases
        return members, bases

    out = {}
    for page in data["pages"]:
        for item in page["items"]:
            members = {m["name"] for m in item.get("methods", []) + item.get("attributes", [])}
            bases = set(item.get("bases") or [])
            if item.get("live_object"):
                members |= common
            module, name = origin.get(item["name"], (None, None))
            node = modules.setdefault(module, Module(module)).defs.get(name) if module else None
            if isinstance(node, ast.ClassDef):
                more_members, more_bases = private_bases(module, node)
                members |= more_members
                bases |= more_bases
                # Class constants (``Platform.GROUPS``), which the reference doesn't list as attributes.
                members |= {t.id for s in node.body if isinstance(s, ast.Assign) for t in s.targets
                            if isinstance(t, ast.Name) and t.id.isupper()}
            out[item["name"]] = {"kind": item["kind"], "bases": sorted(bases), "members": sorted(members)}
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the reference at --out is stale")
    parser.add_argument("--surface", action="store_true", help="print the public surface as JSON instead")
    parser.add_argument("--out", type=Path, help="write the reference to this file instead of printing it")
    args = parser.parse_args(argv)
    if args.surface:
        print(json.dumps(surface(build()), indent=1, sort_keys=True))
        return 0
    if args.check and args.out is None:
        parser.error("--check needs --out, the reference to compare")
    text = render(build())
    if args.check:
        current = args.out.read_text() if args.out.exists() else ""
        if current != text:
            print(f"{args.out} is out of date: run this script with --out {args.out}", file=sys.stderr)
            return 1
        return 0
    if args.out is None:
        sys.stdout.write(text)
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
