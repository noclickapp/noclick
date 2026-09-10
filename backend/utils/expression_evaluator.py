"""
Inline expression evaluation for workflow config fields.

A config-field string may contain ``{{ ... }}`` blocks. Each block is one of three
kinds, classified deterministically (no guessing / try-catch fallback):

  1. Legacy path reference — ``{{node-1.field}}`` where the first segment is a known
     node id (or the reserved ``vars``). Left UNTOUCHED here; the existing sync
     reference resolver (``utils.reference_resolver`` / the execution handlers)
     resolves it exactly as before.
  2. JS expression — uses a ``$``-accessor (``$('node')``, ``$json``, ``$vars``,
     ``$if``, ``$ifEmpty``, ``$now``). Evaluated as JavaScript in the QuickJS sandbox.
  3. Literal passthrough — anything else (e.g. ``{{name}}`` placeholders meant for a
     downstream templating system). Left UNTOUCHED (today's behaviour).

Only kind (2) is handled here; (1) and (3) pass through verbatim, so a config with
no ``$``-expression is byte-for-byte unaffected and triggers zero JS evaluation.
Data reaches the sandbox only through the executor's ``inputs`` object (JSON-encoded
by the executor) — node values are NEVER spliced into the JS source.
"""

import asyncio
import json
import re
from typing import Any, Dict, Iterable, List, Mapping, NamedTuple, Optional, Tuple

from utils.js_executor import execute_js_async

EXPRESSION_TIMEOUT_SEC = 3

# A `$`-accessor signals an intended NoClick expression (kind 2). Matches a `$(`
# call or one of our named accessors as a word. Deliberately does NOT match a bare
# `$5`, so `{{ price is $5 }}` stays a literal passthrough.
_ACCESSOR_RE = re.compile(r"\$\(|\$(?:ifEmpty|vars|json|now|if)\b")
# Legacy path-reference grammar: `nodeId.path.to[0].field`, `nodeId.items[].x`.
_LEGACY_PATH_RE = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_]+|\[\d+\]|\[\])*$")
# Literal `$('id')` / `$("id")` accessor arguments inside an expression.
_REF_ARG_RE = re.compile(r"""\$\(\s*['"]([^'"]+)['"]\s*\)""")
# The first property read off a `$('id')` accessor — `$('t').payload` or
# `$('t')['payload']` — names the missing key in an unresolved-reference error.
# Deliberately one hop deep: "output has no key 'chat_id'; its keys are …" is
# what makes the message fixable without opening the run.
_REF_FIRST_KEY_RE = re.compile(
    r"""\$\(\s*['"][^'"]+['"]\s*\)\s*(?:\.(?P<dot>[A-Za-z_$][\w$]*)|\[\s*['"](?P<bracket>[^'"]+)['"]\s*\])"""
)
# JS `undefined` cannot cross the sandbox boundary (it serialises to null), so an
# evaluated block returns this marker object instead and _eval_block maps it back
# to UNDEFINED. Null stays null; the two are reported with different reasons.
_UNDEFINED_MARKER_KEY = "__nc_undefined__"


class _Undefined:
    """The result of an expression that evaluated to JS ``undefined`` — a key
    the referenced output does not have. Never leaves this module: the
    evaluated config carries None, and callers learn about it through the
    ``unresolved`` channel of :func:`evaluate_expressions`."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNDEFINED"


UNDEFINED = _Undefined()


class UnresolvedReference(NamedTuple):
    """A whole-field expression that produced no value.

    ``path`` is the config path (``to``, ``headers[0].value``); ``reason`` is
    ``"undefined"`` (the referenced output has no such key) or ``"null"`` (the
    key exists and holds null). Partial interpolations (``"Hi {{ … }}"``) are
    not recorded — their empty splice is the long-standing lenient behaviour.
    """

    path: str
    expression: str
    reason: str


# A `nodeId.<rest>` that starts with a node id then a `.field` / `[idx]` (the rest may
# be arbitrary JS). Used to upgrade the bare `{{node.field.method()}}` mistake — JS
# appended to the `{{node.field}}` form instead of using `$('node')` — to the accessor
# form so it evaluates instead of passing through as a literal.
_LEADING_NODE_RE = re.compile(r"^([A-Za-z0-9_-]+)((?:\.[A-Za-z_$][\w$]*|\[\d+\]).*)\Z", re.DOTALL)

# Fixed JS preamble exposing the `$`-accessors. `inputs` is declared by the executor
# in the enclosing scope; the helpers read node data from it (never from source).
# `$` throws a clear error for an unknown node id so a typo'd / unconnected reference
# fails with an actionable message instead of a downstream "undefined" TypeError.
_PREAMBLE = (
    "function $(id){ if (!Object.prototype.hasOwnProperty.call(inputs, id)) "
    "throw new Error(\"No data for node '\" + id + \"' — is it connected upstream and has it run?\"); "
    "return inputs[id]; }\n"
    "const $vars = inputs['vars'] || {};\n"
    "const $json = inputs['__primary_input__'] || {};\n"
    "function $if(c, a, b){ return c ? a : b; }\n"
    "function $ifEmpty(v, f){ return (v === undefined || v === null || v === '') ? f : v; }\n"
    "const $now = new Date();\n"
)


class ExpressionEvaluationError(ValueError):
    """Raised when a ``{{ ... }}`` JS expression fails to evaluate (syntax error,
    runtime error, or timeout). Surfaced at the node boundary as the node's error."""

    def __init__(self, expression: str, message: str):
        self.expression = expression
        self.js_error = message
        super().__init__(f"Expression {{{{ {expression} }}}} failed: {message}")


def is_legacy_path_reference(inner: str, node_outputs: Dict[str, Any]) -> bool:
    """True if ``inner`` is a plain path reference whose first segment is a known
    node id / the reserved ``vars`` — i.e. resolvable by the legacy path resolver."""
    inner = inner.strip()
    if not _LEGACY_PATH_RE.match(inner):
        return False
    first = re.split(r"[.\[]", inner, maxsplit=1)[0]
    return first in node_outputs


def _is_js_expression(inner: str) -> bool:
    return bool(_ACCESSOR_RE.search(inner))


def _as_js_expression(inner: str, node_outputs: Dict[str, Any]) -> Optional[str]:
    """The JS-ready form of a ``{{ }}`` block, or None if it isn't JS.

    - A ``$``-accessor expression is returned as-is.
    - A plain legacy data path (``node.field``) returns None — the sync resolver owns it.
    - A bare ``nodeId.<js>`` whose leading id is a known node (the common
      ``{{node.field.toUpperCase()}}`` mistake) is upgraded to ``$('nodeId').<js>`` so it
      evaluates instead of passing through as a literal.
    - Anything else (literal text) returns None.
    """
    s = inner.strip()
    if _is_js_expression(s):
        return s
    if is_legacy_path_reference(s, node_outputs):
        return None
    m = _LEADING_NODE_RE.match(s)
    if m and m.group(1) in node_outputs:
        return f"$('{m.group(1)}'){m.group(2)}"
    return None


def is_js_expression(inner: str) -> bool:
    """True if a ``{{ }}`` inner is a ``$``-accessor JS expression (not a legacy
    dotted path or a literal). Public wrapper for reference-validation call sites."""
    return _is_js_expression(inner)


def extract_expression_node_ids(inner: str) -> List[str]:
    """Node ids a JS expression reads via ``$('id')`` accessors, in first-seen order.

    Excludes ``$vars``/``$json`` (not nodes) and dynamic ``$(var)`` args (no literal id).
    Reference validators use this: a ``$()`` expression's property chain is JavaScript, so
    only its ``$('id')`` data sources are graph-validatable — the ``.field.length`` tail is
    code, not a navigable data path."""
    seen: List[str] = []
    for m in _REF_ARG_RE.finditer(inner):
        nid = m.group(1)
        if nid not in seen:
            seen.append(nid)
    return seen


def _scan_blocks(value: str) -> List[Tuple[int, int, str]]:
    """Find every top-level ``{{ ... }}`` block, tolerating inner ``}`` (object
    literals, arrow bodies) and brace-bearing string/template literals. Returns
    ``(start, end, inner)`` spans where ``end`` is just past the closing ``}}``.
    The naive ``\\{\\{([^}]+)\\}\\}`` regex cannot do this — it stops at the first
    ``}``."""
    blocks: List[Tuple[int, int, str]] = []
    i, n = 0, len(value)
    while i < n - 1:
        if value[i] == "{" and value[i + 1] == "{":
            inner_start = i + 2
            j = inner_start
            depth = 0
            quote = ""
            while j < n:
                c = value[j]
                if quote:
                    if c == "\\":
                        j += 2
                        continue
                    if c == quote:
                        quote = ""
                    j += 1
                    continue
                if c in "'\"`":
                    quote = c
                elif c == "{":
                    depth += 1
                elif c == "}":
                    if depth > 0:
                        depth -= 1
                    elif j + 1 < n and value[j + 1] == "}":
                        blocks.append((i, j + 2, value[inner_start:j]))
                        break
                j += 1
            i = j + 2 if j < n else n
        else:
            i += 1
    return blocks


def _stringify(v: Any) -> str:
    """Stringify a computed value for substitution into surrounding text. Matches
    the existing reference convention (``''`` for null) but JSON-encodes
    objects/arrays so they don't leak Python repr."""
    if v is None or v is UNDEFINED:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    try:
        return json.dumps(v)
    except (TypeError, ValueError):
        return str(v)


def _build_inputs(
    inner: str,
    node_outputs: Dict[str, Any],
    workflow_nodes: Optional[List[Dict[str, Any]]],
    primary_input: Any,
) -> Dict[str, Any]:
    """Build the ``inputs`` object passed to the sandbox: the node outputs the
    expression's ``$('...')`` literals reference (keyed by the exact arg string, so
    both ids and labels resolve), plus ``vars`` and the ``$json`` primary input."""
    label_to_id: Dict[str, str] = {}
    for node in workflow_nodes or []:
        nid = node.get("id")
        label = (node.get("data") or {}).get("label")
        if nid and label:
            label_to_id.setdefault(label, nid)

    inputs: Dict[str, Any] = {}
    args = _REF_ARG_RE.findall(inner)
    # A `$(` whose arg isn't a string literal (dynamic id) — include everything.
    if inner.count("$(") > len(args):
        inputs.update(node_outputs)
        for label, nid in label_to_id.items():
            if nid in node_outputs and label not in inputs:
                inputs[label] = node_outputs[nid]
    else:
        for arg in args:
            if arg in node_outputs:
                inputs[arg] = node_outputs[arg]
            elif arg in label_to_id and label_to_id[arg] in node_outputs:
                inputs[arg] = node_outputs[label_to_id[arg]]
            # Missing node ids are deliberately left out so `$(id)` raises a clear
            # "No data for node" error rather than silently resolving to null.

    inputs["vars"] = node_outputs.get("vars", {})
    inputs["__primary_input__"] = primary_input if primary_input is not None else {}
    return inputs


async def _eval_block(
    inner: str,
    node_outputs: Dict[str, Any],
    workflow_nodes: Optional[List[Dict[str, Any]]],
    primary_input: Any,
) -> Any:
    expr = inner.strip()
    inputs = _build_inputs(inner, node_outputs, workflow_nodes, primary_input)
    # The newline before `)` keeps a trailing `// comment` in the expression
    # from swallowing the close paren.
    code = (
        _PREAMBLE
        + f"const __nc_value = ({expr}\n);\n"
        + f"return __nc_value === undefined ? {{{json.dumps(_UNDEFINED_MARKER_KEY)}: true}} : __nc_value;"
    )
    result = await execute_js_async(code=code, inputs=inputs, timeout_sec=EXPRESSION_TIMEOUT_SEC)
    if not result.get("success"):
        raise ExpressionEvaluationError(expr, result.get("error") or "unknown error")
    value = result.get("result")
    if isinstance(value, dict) and len(value) == 1 and value.get(_UNDEFINED_MARKER_KEY) is True:
        return UNDEFINED
    return value


async def _evaluate_string(
    value: str,
    node_outputs: Dict[str, Any],
    workflow_nodes: Optional[List[Dict[str, Any]]],
    primary_input: Any,
    path: str = "",
    unresolved: Optional[List[UnresolvedReference]] = None,
) -> Any:
    if "{{" not in value:
        return value

    js_blocks: List[Tuple[int, int, str]] = []
    for (s, e, inner) in _scan_blocks(value):
        js = _as_js_expression(inner, node_outputs)
        if js is not None:
            js_blocks.append((s, e, js))  # may be the upgraded `$()` form
    if not js_blocks:
        return value  # only legacy/literal blocks — leave for the sync resolver

    # Full-match: the entire field is exactly one JS block → preserve the raw type.
    # A block that produced nothing leaves the whole field EMPTY, which is only
    # ever right for an optional field — so it is reported and the caller decides.
    if len(js_blocks) == 1:
        s, e, inner = js_blocks[0]
        if value[:s].strip() == "" and value[e:].strip() == "":
            result = await _eval_block(inner, node_outputs, workflow_nodes, primary_input)
            if result is UNDEFINED or result is None:
                if unresolved is not None:
                    reason = "undefined" if result is UNDEFINED else "null"
                    unresolved.append(UnresolvedReference(path, inner.strip(), reason))
                return None
            return result

    # Partial: evaluate each JS block, stringify, and splice into the surrounding
    # text. Non-JS spans (legacy refs, literals, plain text) are kept verbatim.
    results = await asyncio.gather(
        *[_eval_block(inner, node_outputs, workflow_nodes, primary_input) for (_, _, inner) in js_blocks]
    )
    out: List[str] = []
    last = 0
    for (s, e, _inner), result in zip(js_blocks, results):
        out.append(value[last:s])
        out.append(_stringify(result))
        last = e
    out.append(value[last:])
    return "".join(out)


_PREVIEW_STRING_MAX = 120


def format_preview_tokens(data: Any, depth: int = 4) -> List[Dict[str, str]]:
    """Render a value as a compact, bounded sequence of typed tokens for the expression
    editor's output preview. Each token is ``{"t": <type>, "v": <text>}`` where type is
    one of key | str | num | bool | null | punct | meta — letting the UI highlight keys
    (and lightly tint values) without re-parsing the string. Long strings are truncated;
    arrays lead with their COUNT plus the first couple of items; objects show their first
    few keys."""
    if depth <= 0:
        return [{"t": "meta", "v": "…"}]
    if data is None:
        return [{"t": "null", "v": "null"}]
    if isinstance(data, bool):
        return [{"t": "bool", "v": "true" if data else "false"}]
    if isinstance(data, (int, float)):
        return [{"t": "num", "v": repr(data)}]
    if isinstance(data, str):
        s = data if len(data) <= _PREVIEW_STRING_MAX else data[:_PREVIEW_STRING_MAX] + "…"
        return [{"t": "str", "v": s}]
    if isinstance(data, list):
        n = len(data)
        if n == 0:
            return [{"t": "meta", "v": "[] (empty list)"}]
        toks: List[Dict[str, str]] = [{"t": "meta", "v": f"{n} item{'' if n == 1 else 's'}: "}, {"t": "punct", "v": "["}]
        for i, x in enumerate(data[:2]):
            if i:
                toks.append({"t": "punct", "v": ", "})
            toks.extend(format_preview_tokens(x, depth - 1))
        if n > 2:
            toks.append({"t": "meta", "v": f", … +{n - 2} more"})
        toks.append({"t": "punct", "v": "]"})
        return toks
    if isinstance(data, dict):
        items = list(data.items())
        toks = [{"t": "punct", "v": "{"}]
        for i, (k, v) in enumerate(items[:6]):
            if i:
                toks.append({"t": "punct", "v": ", "})
            toks.append({"t": "key", "v": str(k)})
            toks.append({"t": "punct", "v": ": "})
            toks.extend(format_preview_tokens(v, depth - 1))
        if len(items) > 6:
            toks.append({"t": "meta", "v": f", … +{len(items) - 6} more keys"})
        toks.append({"t": "punct", "v": "}"})
        return toks
    return [{"t": "str", "v": str(data)}]


def format_preview(data: Any, depth: int = 4) -> str:
    """Flat-string form of ``format_preview_tokens`` (same bounded compact preview)."""
    return "".join(t["v"] for t in format_preview_tokens(data, depth))


async def evaluate_single_expression(
    expression: str,
    node_outputs: Dict[str, Any],
    *,
    workflow_nodes: Optional[List[Dict[str, Any]]] = None,
    primary_input: Any = None,
) -> Any:
    """Evaluate a bare expression (no surrounding ``{{ }}``) as JavaScript. Used by
    the live-preview editor, where the input is always an expression regardless of
    whether it uses a ``$``-accessor. Empty input returns None. Raises
    ``ExpressionEvaluationError`` on failure."""
    if not expression.strip():
        return None
    # Upgrade a bare `node.field.method()` to `$('node')...`; otherwise eval as-is (the
    # preview always treats its input as JS, accessor or not).
    expr = _as_js_expression(expression, node_outputs) or expression
    result = await _eval_block(expr, node_outputs, workflow_nodes, primary_input)
    return None if result is UNDEFINED else result


async def evaluate_expressions(
    value: Any,
    node_outputs: Dict[str, Any],
    *,
    workflow_nodes: Optional[List[Dict[str, Any]]] = None,
    primary_input: Any = None,
    unresolved: Optional[List[UnresolvedReference]] = None,
    _path: str = "",
) -> Any:
    """Recursively evaluate ``$``-expression ``{{ ... }}`` blocks in a config value,
    replacing each with its computed value. Legacy path references and literal
    ``{{ }}`` passthroughs are returned untouched for the downstream sync resolver.

    Pass a list as ``unresolved`` to learn which whole-field expressions produced
    no value (:class:`UnresolvedReference`); those fields come back as None.

    Raises ``ExpressionEvaluationError`` if any JS expression fails — the caller
    surfaces it as the node's error.
    """
    if isinstance(value, str):
        return await _evaluate_string(
            value, node_outputs, workflow_nodes, primary_input, _path, unresolved
        )
    if isinstance(value, dict):
        return {
            k: await evaluate_expressions(
                v, node_outputs, workflow_nodes=workflow_nodes, primary_input=primary_input,
                unresolved=unresolved, _path=f"{_path}.{k}" if _path else str(k),
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [
            await evaluate_expressions(
                item, node_outputs, workflow_nodes=workflow_nodes, primary_input=primary_input,
                unresolved=unresolved, _path=f"{_path}[{i}]",
            )
            for i, item in enumerate(value)
        ]
    return value


def _output_keys_summary(output: Any, limit: int = 12) -> str:
    if isinstance(output, dict):
        keys = [str(k) for k in output]
        if not keys:
            return "it is an empty object"
        shown = ", ".join(keys[:limit])
        if len(keys) > limit:
            shown += f", … (+{len(keys) - limit} more)"
        return f"its top-level keys are: {shown}"
    if isinstance(output, list):
        return f"it is a list of {len(output)} items (index with [0])"
    return f"it is a {type(output).__name__} value"


def describe_unresolved_reference(
    ref: UnresolvedReference, node_outputs: Mapping[str, Any]
) -> str:
    """One sentence naming what the expression asked for and what the referenced
    node actually holds — the difference between "resolved to nothing" and a
    fix the reader can make without opening the run."""
    detail = f"{{{{ {ref.expression} }}}} resolved to nothing"
    node_ids = _REF_ARG_RE.findall(ref.expression)
    if not node_ids:
        return detail
    node_id = node_ids[0]
    output = node_outputs.get(node_id)
    if isinstance(output, dict) and output.get("status") == "no_event":
        return (
            f"{detail}: node '{node_id}' has no live event in this run — a manual run "
            f"stores a no-event placeholder, so fire the workflow with a real "
            f"message/webhook to test this path"
        )
    key_match = _REF_FIRST_KEY_RE.search(ref.expression)
    key = key_match and (key_match.group("dot") or key_match.group("bracket"))
    if ref.reason == "null":
        what = f"'{key}' is null" if key else "the value is null"
        return f"{detail}: in node '{node_id}' output {what}"
    what = f"has no key '{key}'" if key else "has no such value"
    return f"{detail}: node '{node_id}' output {what} ({_output_keys_summary(output)})"


def unresolved_required_field_error(
    unresolved: Iterable[UnresolvedReference],
    required_fields: Iterable[str],
    node_outputs: Mapping[str, Any],
) -> Optional[str]:
    """The node error for whole-field references that resolved to nothing in
    REQUIRED fields, or None when every unresolved field is optional.

    An optional field left empty takes its default; a required field left
    empty either fails its parse or — for a str field — is handed to the
    provider as "" (a reply addressed to nobody reported success for 50
    minutes, 2026-09-10). Only top-level fields are judged: the model says
    nothing about the shape inside a list or object field.
    """
    required = set(required_fields)
    hits = [ref for ref in unresolved if ref.path in required]
    if not hits:
        return None
    return "; ".join(
        f"Required field '{ref.path}' is empty — {describe_unresolved_reference(ref, node_outputs)}"
        for ref in hits
    )
