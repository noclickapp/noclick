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
from typing import Any, Dict, List, Optional, Tuple

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
    if v is None:
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
    code = _PREAMBLE + f"return ({expr});"
    result = await execute_js_async(code=code, inputs=inputs, timeout_sec=EXPRESSION_TIMEOUT_SEC)
    if not result.get("success"):
        raise ExpressionEvaluationError(expr, result.get("error") or "unknown error")
    return result.get("result")


async def _evaluate_string(
    value: str,
    node_outputs: Dict[str, Any],
    workflow_nodes: Optional[List[Dict[str, Any]]],
    primary_input: Any,
) -> Any:
    if "{{" not in value:
        return value

    js_blocks = [
        (s, e, inner)
        for (s, e, inner) in _scan_blocks(value)
        if not is_legacy_path_reference(inner, node_outputs) and _is_js_expression(inner)
    ]
    if not js_blocks:
        return value  # only legacy/literal blocks — leave for the sync resolver

    # Full-match: the entire field is exactly one JS block → preserve the raw type.
    if len(js_blocks) == 1:
        s, e, inner = js_blocks[0]
        if value[:s].strip() == "" and value[e:].strip() == "":
            return await _eval_block(inner, node_outputs, workflow_nodes, primary_input)

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
    return await _eval_block(expression, node_outputs, workflow_nodes, primary_input)


async def evaluate_expressions(
    value: Any,
    node_outputs: Dict[str, Any],
    *,
    workflow_nodes: Optional[List[Dict[str, Any]]] = None,
    primary_input: Any = None,
) -> Any:
    """Recursively evaluate ``$``-expression ``{{ ... }}`` blocks in a config value,
    replacing each with its computed value. Legacy path references and literal
    ``{{ }}`` passthroughs are returned untouched for the downstream sync resolver.

    Raises ``ExpressionEvaluationError`` if any JS expression fails — the caller
    surfaces it as the node's error.
    """
    if isinstance(value, str):
        return await _evaluate_string(value, node_outputs, workflow_nodes, primary_input)
    if isinstance(value, dict):
        return {
            k: await evaluate_expressions(
                v, node_outputs, workflow_nodes=workflow_nodes, primary_input=primary_input
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [
            await evaluate_expressions(
                item, node_outputs, workflow_nodes=workflow_nodes, primary_input=primary_input
            )
            for item in value
        ]
    return value
