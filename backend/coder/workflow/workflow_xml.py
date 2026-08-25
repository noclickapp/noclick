"""Shared XML parser for the public workflow-operation vocabulary."""

import html
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


# ============================================================================
# Data structures
# ============================================================================

@dataclass
class XmlOp:
    """A parsed XML operation."""
    tag: str
    attrs: Dict[str, str] = field(default_factory=dict)
    body: Optional[str] = None


# ============================================================================
# Tag vocabulary
# ============================================================================

ALL_TAGS: Set[str] = {
    # Graph mutations
    'add_node', 'add_edge', 'remove_node', 'remove_edge',
    # Config
    'field', 'patch',
    # Credentials & state
    'set_credentials', 'disable_node', 'enable_node',
    'mock_node', 'unmock_node',
    # Node execution settings (retry, error handling, notes, etc.)
    'update_settings',
    # Pass-specific
    'done', 'input', 'ask', 'update_goal',
    # Agentic queries
    'query_operations', 'query_schema', 'search_credentials', 'read',
    # Agentic output
    'message',
    # Sticky notes
    'add_sticky_note',
    # Workflow management (agentic)
    'list_workflows', 'open_workflow', 'create_workflow',
    # Folder management (agentic)
    'list_folders', 'create_folder', 'delete_folder', 'move_workflow',
    # Config inspection (agentic)
    'read_config',
    # Node output and execution (agentic)
    'get_output', 'run_node',
    # Workflow variables + test runs (settings-level content)
    'define_variable', 'add_test_run', 'run_test',
    # Deprecated aliases (backward compat)
    'update_config', 'patch_config',
}

_ALL_TAGS_RE = '|'.join(sorted(ALL_TAGS, key=len, reverse=True))

# Tags that support body content: <tag attrs>body</tag>
_BODY_TAGS: Set[str] = {
    'field', 'patch', 'mock_node',
    # Sticky notes
    'add_sticky_note',
    # Agentic
    'message', 'input', 'ask',
    # Workflow variables + test runs (body = value / staged message body)
    'define_variable', 'add_test_run',
    # Deprecated
    'update_config', 'patch_config',
}

_BODY_TAGS_RE = '|'.join(sorted(_BODY_TAGS, key=len, reverse=True))


# ============================================================================
# Regex patterns
# ============================================================================

# Attribute: key="value" or key='value' with backslash-escape support
_ATTR_PATTERN = re.compile(
    r'(\w+)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\')'
)

# Self-closing or non-body opening tags: <tag attrs /> or <tag attrs>
# Supports both key="value" attributes and bare boolean attributes (e.g., "full")
# The attribute repetition is possessive (`*+`): without it, a tag name in our
# vocabulary followed by attributes we can't parse (JSX `<input value={v} />` —
# `input` is in ALL_TAGS) makes the trailing `\s*/?>` fail, and the engine then
# re-partitions the attribute run exponentially. That cost 2s+ per 100KB of
# streamed interface-html-react JSX and pinned whole containers. Possessive
# fails the match immediately instead; a successful match never needs to give
# characters back, since `\w+` cannot consume the `/`, `>` or space the tail needs.
_TAG_PATTERN = re.compile(
    rf'<({_ALL_TAGS_RE})\s+((?:(?:\w+\s*=\s*(?:"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')|\w+)\s*)*+)\s*/?>'
)

# Zero-attribute self-closing tags like <done/> or <done />
_BARE_TAG_PATTERN = re.compile(
    rf'<({_ALL_TAGS_RE})\s*/?>'
)

# Body tags: <tag attrs>body</tag> (supports zero attributes like <message>text</message>).
# Attributes mirror _TAG_PATTERN — key="value" plus bare booleans (e.g.
# `per_user` in <define_variable name="x" per_user>v</define_variable>), with
# the same possessive repetition to avoid exponential re-partitioning on
# attribute runs we can't parse.
_BODY_TAG_PATTERN = re.compile(
    rf'<({_BODY_TAGS_RE})\s*((?:(?:\w+\s*=\s*(?:"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')|\w+)\s*)*+)\s*>([\s\S]*?)</\1>'
)

# Start of any recognized tag — used to bound the implicit body of an
# unclosed open tag during final-parse recovery.
_NEXT_TAG_OPEN_PATTERN = re.compile(rf'<({_ALL_TAGS_RE})[\s/>]')


# ============================================================================
# Unescaping & value coercion
# ============================================================================

def unescape_attr_value(value: str) -> str:
    """Unescape a raw XML attribute value.

    Handles backslash escapes (\\", \\', \\n, \\t, \\r, \\\\) then HTML entities.
    """
    # Character-by-character backslash unescape
    result = []
    i = 0
    while i < len(value):
        if value[i] == '\\' and i + 1 < len(value):
            nxt = value[i + 1]
            if nxt == 'n':
                result.append('\n')
                i += 2
            elif nxt == 't':
                result.append('\t')
                i += 2
            elif nxt == 'r':
                result.append('\r')
                i += 2
            elif nxt == '\\':
                result.append('\\')
                i += 2
            elif nxt == '"':
                result.append('"')
                i += 2
            elif nxt == "'":
                result.append("'")
                i += 2
            else:
                result.append(value[i])
                i += 1
        else:
            result.append(value[i])
            i += 1
    unescaped = ''.join(result)

    # HTML entity unescape
    return html.unescape(unescaped)


def coerce_value(value: str) -> Any:
    """Try json.loads() first (handles numbers, booleans, arrays, objects), fall back to string.

    Also handles Python-style literals (single quotes, True/False/None) that LLMs
    sometimes output instead of strict JSON.
    """
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        pass
    # LLMs often output a mix of JSON and Python syntax (single quotes + null/true/false).
    # Normalize JSON keywords to Python equivalents, then parse with ast.literal_eval.
    if value and value[0] in ('{', '[', '('):
        try:
            import ast
            import re
            # Replace JSON keywords with Python equivalents (only outside quoted strings)
            # Simple approach: replace word-boundary null/true/false
            normalized = re.sub(r'\bnull\b', 'None', value)
            normalized = re.sub(r'\btrue\b', 'True', normalized)
            normalized = re.sub(r'\bfalse\b', 'False', normalized)
            return ast.literal_eval(normalized)
        # Double-braced builder values can parse as a set containing another
        # set (for example ``{{1, 2}}``).  ``literal_eval`` raises TypeError
        # while constructing that unhashable outer set; treat it like the
        # other non-literal inputs and preserve the original string.
        except (TypeError, ValueError, SyntaxError):
            pass
    return value


def coerce_value_for_field(raw_value: str, field_schema: Optional[Dict[str, Any]]) -> Any:
    """Like ``coerce_value`` but schema-aware: keep the raw string when the
    target field is declared as a string (typed or enum-of-strings).

    Bare ``coerce_value`` JSON-parses ``"false"`` → Python ``False`` and
    ``"42"`` → ``42``. That's correct for boolean/integer fields but breaks
    string-typed fields like ``show_in_interface: enum('true','false')`` —
    Pydantic v2 rejects ``False`` for a ``str`` field. Looking at the field's
    schema before coercing avoids the loop where the AI builder writes
    ``value="false"`` and Pydantic keeps rejecting it.

    Args:
        raw_value: The XML attribute / body string from the LLM.
        field_schema: The field's JSON Schema (a ``schema["properties"][name]``
            entry). May be ``None`` if the schema isn't available — in which
            case we fall back to ``coerce_value``.

    Returns:
        Either ``raw_value`` unchanged (when the field is string-typed) or the
        result of ``coerce_value``.
    """
    if not raw_value:
        return raw_value
    if field_schema:
        enum_values = field_schema.get("enum")
        field_type = field_schema.get("type")
        # Enum-of-strings: keep as string even if the token (e.g. "true") would
        # otherwise JSON-decode to a bool.
        if enum_values and all(isinstance(v, str) for v in enum_values):
            return raw_value
        # Plain string field — don't accidentally turn "42" into an int.
        if field_type == "string":
            return raw_value
    return coerce_value(raw_value)


def escape_xml_attr(value: str) -> str:
    """Escape a string for use inside XML attribute double quotes."""
    return (value
            .replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


# ============================================================================
# Internal helpers
# ============================================================================

def _parse_attrs(attrs_str: str) -> Dict[str, str]:
    """Parse an attribute string into {name: unescaped_value} dict.

    Handles both key="value" attributes and bare boolean attributes
    (e.g., ``full`` in ``<get_output node="x" full />``).
    """
    attrs: Dict[str, str] = {}
    matched_spans: list = []
    for m in _ATTR_PATTERN.finditer(attrs_str):
        val = m.group(2) if m.group(2) is not None else m.group(3)
        attrs[m.group(1)] = unescape_attr_value(val)
        matched_spans.append((m.start(), m.end()))
    # Bare boolean attributes — words not inside a key=value span
    for m in re.finditer(r'\b([a-zA-Z_]\w*)\b', attrs_str):
        if m.group(1) in attrs:
            continue
        if any(s <= m.start() < e for s, e in matched_spans):
            continue
        attrs[m.group(1)] = ''
    return attrs


def _find_tag_end(text: str) -> int:
    """Find the index of > that closes a tag, tracking bracket/quote depth.

    Handles unescaped quotes inside bracket-nested values like:
      name="x" value="[{"a": 1}]" />
    Returns index of the closing > or -1 if not found.
    """
    depth = 0
    in_quote = None  # None, '"', or "'"
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if in_quote:
            if c == '\\' and i + 1 < n:
                i += 2
                continue
            if c in ('{', '['):
                depth += 1
            elif c in ('}', ']'):
                depth = max(0, depth - 1)
            elif c == in_quote and depth == 0:
                in_quote = None
        elif c in ('"', "'"):
            in_quote = c
        elif c == '>':
            return i
        i += 1
    return -1


def _parse_attrs_nested(attrs_str: str) -> Dict[str, str]:
    """Parse attributes with bracket-aware quote matching.

    Handles unescaped double quotes inside JSON values like:
      value="[{"frequency": "weekly"}]"
    by tracking {}/[] depth — inner quotes don't terminate the attribute.
    """
    attrs: Dict[str, str] = {}
    i = 0
    n = len(attrs_str)
    while i < n:
        # Skip whitespace
        while i < n and attrs_str[i] in ' \t\n\r':
            i += 1
        if i >= n:
            break
        # Match key
        key_start = i
        while i < n and attrs_str[i] not in '= \t\n\r':
            i += 1
        key = attrs_str[key_start:i]
        if not key:
            break
        # Skip whitespace and =
        while i < n and attrs_str[i] in ' \t\n\r':
            i += 1
        if i >= n or attrs_str[i] != '=':
            # Bare boolean attribute (e.g., "full" in <get_output node="x" full />)
            if key.isidentifier():
                attrs[key] = ''
            continue
        i += 1  # skip =
        while i < n and attrs_str[i] in ' \t\n\r':
            i += 1
        if i >= n:
            break
        # Parse value with bracket-depth tracking
        quote = attrs_str[i]
        if quote not in ('"', "'"):
            break
        i += 1  # skip opening quote
        depth = 0
        val_start = i
        while i < n:
            c = attrs_str[i]
            if c == '\\' and i + 1 < n:
                i += 2  # skip escaped char
                continue
            if c in ('{', '['):
                depth += 1
            elif c in ('}', ']'):
                depth = max(0, depth - 1)
            elif c == quote and depth == 0:
                break  # real closing quote
            i += 1
        val = attrs_str[val_start:i]
        attrs[key] = unescape_attr_value(val)
        if i < n:
            i += 1  # skip closing quote
    return attrs


# ============================================================================
# Full-text parser
# ============================================================================

_TAG_RE_NESTED = re.compile(rf'<({_ALL_TAGS_RE})\s')


def _parse_xml_impl(
    text: str,
    allowed_tags: Optional[Set[str]],
    rejected_tags: Optional[Set[str]],
    start_offset: int,
    final: bool = False,
) -> Tuple[List[XmlOp], int]:
    """Parse XML operations from text[start_offset:]. Returns (ops, next_safe_offset).

    Four-pass approach, collecting into a position-keyed dict for document-order output:
      1. Body tags (<tag attrs>body</tag>) — record their spans.
      2. Self-closing / opening tags with attributes — skip overlaps with body spans.
         Opening (non-self-closing) body-eligible tags whose </tag> hasn't arrived
         are tracked as pending barriers and NOT emitted.
      3. Bare tags with no attributes (<done/>) — skip overlaps with body spans and the attribute scan.
      4. Fallback for tags with unescaped quotes (e.g. value="[{"a": 1}]").

    When ``final`` is True the text is a complete response (not a growing
    stream buffer), so a body-eligible tag whose </tag> never arrived is
    recovered instead of dropped: with a value= attribute it's treated as
    self-closing (LLMs routinely emit ``<field ... type="static">`` with a
    bare ``>``), otherwise the text up to the next recognized tag becomes its
    body. Streaming callers keep the deferral — the closing tag may simply
    not have arrived yet.

    next_safe_offset is the position past which all earlier tags have been resolved
    and the caller may slice/forget. It will not advance past any unclosed body-tag
    opening or any partial '<...' suffix at the end of the buffer.
    """
    positions: Dict[int, XmlOp] = {}
    body_spans: Set[Tuple[int, int]] = set()
    tag_spans: Set[Tuple[int, int]] = set()
    open_body_starts: Set[int] = set()
    # start → (tag, attrs, content_start) for allowed body-eligible opens whose
    # closing tag never arrived; recovered after Pass 4 when final.
    pending_opens: Dict[int, Tuple[str, Dict[str, str], int]] = {}

    # builder: body tags
    for m in _BODY_TAG_PATTERN.finditer(text, pos=start_offset):
        tag = m.group(1)
        if allowed_tags and tag not in allowed_tags:
            if rejected_tags is not None:
                rejected_tags.add(tag)
            # Record the span so streaming-mode barrier detection can skip past
            # this fully-resolved (just filtered-out) construct.
            body_spans.add((m.start(), m.end()))
            continue
        # Handle CDATA sections and HTML entity escaping in body content.
        # CDATA: <tag><![CDATA[raw content]]></tag> — strip markers, use raw.
        # Entities: <tag>&lt;div&gt;</tag> — unescape to <div>.
        raw_body = m.group(3).strip()
        if raw_body.startswith('<![CDATA[') and raw_body.endswith(']]>'):
            body_text = raw_body[9:-3]  # Strip <![CDATA[ and ]]>, keep raw
        else:
            body_text = html.unescape(raw_body)
        positions[m.start()] = XmlOp(
            tag=tag, attrs=_parse_attrs(m.group(2)), body=body_text
        )
        body_spans.add((m.start(), m.end()))

    def _overlaps_body(start: int) -> bool:
        return any(s <= start < e for s, e in body_spans)

    # node drafter: self-closing / opening tags with attributes
    for m in _TAG_PATTERN.finditer(text, pos=start_offset):
        if _overlaps_body(m.start()):
            continue
        tag = m.group(1)
        is_self_closing = m.group(0).rstrip().endswith('/>')
        if allowed_tags and tag not in allowed_tags:
            if rejected_tags is not None:
                rejected_tags.add(tag)
            # Record span (even for filtered tags) so streaming barrier
            # detection can skip past them. Body-eligible opens without close
            # remain pending so we don't advance past an unfinished tag.
            if is_self_closing or tag not in _BODY_TAGS:
                tag_spans.add((m.start(), m.end()))
            else:
                open_body_starts.add(m.start())
            continue
        # Body-eligible opening tags without '/' close are pending — defer until
        # </tag> arrives via builder. Emitting them now would surface partial
        # XmlOps (no body, no value) and stick the caller's dedup state.
        if not is_self_closing and tag in _BODY_TAGS:
            open_body_starts.add(m.start())
            if final:
                pending_opens[m.start()] = (tag, _parse_attrs(m.group(2)), m.end())
            continue
        if m.start() not in positions:
            positions[m.start()] = XmlOp(tag=tag, attrs=_parse_attrs(m.group(2)))
        tag_spans.add((m.start(), m.end()))

    # node drafter: bare tags with no attributes (e.g. <done/>)
    for m in _BARE_TAG_PATTERN.finditer(text, pos=start_offset):
        if _overlaps_body(m.start()):
            continue
        if any(s <= m.start() < e for s, e in tag_spans):
            continue
        tag = m.group(1)
        if allowed_tags and tag not in allowed_tags:
            if rejected_tags is not None:
                rejected_tags.add(tag)
            tag_spans.add((m.start(), m.end()))
            continue
        if m.start() not in positions:
            positions[m.start()] = XmlOp(tag=tag, attrs={})
        tag_spans.add((m.start(), m.end()))

    # Pass 4: fallback for tags with unescaped quotes in attribute values.
    # When the LLM writes value="[{"key": "val"}]", the regex-based passes fail
    # because inner " terminates the attribute prematurely. Scan for <tagname
    # sequences not already matched and parse with bracket-depth-aware parser.
    all_spans = body_spans | tag_spans | {(p, p) for p in positions}
    for m in _TAG_RE_NESTED.finditer(text, pos=start_offset):
        if any(s <= m.start() < e for s, e in all_spans):
            continue
        if m.start() in positions or m.start() in open_body_starts:
            continue
        tag = m.group(1)
        # Compute the tag's span once so we can record it whether or not the tag
        # passes the allowed_tags filter — streaming barrier detection needs
        # filtered-out tags to look "resolved" rather than partial.
        rest = text[m.end():]
        end_idx = _find_tag_end(rest)
        if allowed_tags and tag not in allowed_tags:
            if rejected_tags is not None:
                rejected_tags.add(tag)
            if end_idx >= 0:
                tag_spans.add((m.start(), m.end() + end_idx + 1))
            else:
                open_body_starts.add(m.start())
            continue
        # Find the closing > or /> using bracket-depth tracking
        if end_idx < 0:
            # Unclosed tag '<x ' with no '>' yet — leave as a barrier.
            open_body_starts.add(m.start())
            continue
        tag_content = rest[:end_idx]
        is_self_closing = tag_content.rstrip().endswith('/')
        attrs_str = tag_content.rstrip().rstrip('/')
        attrs = _parse_attrs_nested(attrs_str)
        if not attrs:
            continue
        abs_end = m.end() + end_idx + 1  # position after >
        # Body-eligible opening tag with no '/': defer until </tag> arrives.
        if tag in _BODY_TAGS and not is_self_closing:
            close_tag = f'</{tag}>'
            close_idx = text.find(close_tag, abs_end)
            if close_idx < 0:
                open_body_starts.add(m.start())
                if final:
                    pending_opens[m.start()] = (tag, attrs, abs_end)
                continue
            raw_body = text[abs_end:close_idx].strip()
            body = html.unescape(raw_body) if raw_body else ""
            positions[m.start()] = XmlOp(tag=tag, attrs=attrs, body=body)
            tag_spans.add((m.start(), close_idx + len(close_tag)))
        else:
            positions[m.start()] = XmlOp(tag=tag, attrs=attrs, body=None)
            tag_spans.add((m.start(), abs_end))

    # Final-parse recovery: emit body-eligible opens whose </tag> never arrived.
    if final:
        for start, (tag, attrs, content_start) in pending_opens.items():
            if start in positions or _overlaps_body(start):
                continue
            if 'value' in attrs:
                # Value already in the attribute — the missing '/' was the only flaw.
                positions[start] = XmlOp(tag=tag, attrs=attrs, body=None)
            else:
                nxt = _NEXT_TAG_OPEN_PATTERN.search(text, content_start)
                body_end = nxt.start() if nxt else len(text)
                raw_body = text[content_start:body_end].strip()
                positions[start] = XmlOp(
                    tag=tag, attrs=attrs, body=html.unescape(raw_body) if raw_body else "",
                )

    # Compute next_safe_offset: smallest position that's still "in flight."
    # Barriers are (a) unclosed body-tag openings and (b) any '<' after start_offset
    # not matched by a closed tag span (e.g. partial '<fie' at buffer tail).
    closed_span_by_start: Dict[int, int] = {s: e for s, e in body_spans}
    for s, e in tag_spans:
        # Prefer the larger end if a position has both builder and node drafter spans.
        prev = closed_span_by_start.get(s)
        if prev is None or e > prev:
            closed_span_by_start[s] = e

    barrier = len(text)
    if open_body_starts:
        barrier = min(barrier, min(open_body_starts))

    # Walk '<' occurrences from start_offset, jumping past closed spans, until we
    # hit one that's neither a closed-tag start nor an open-body-start.
    i = start_offset
    n = len(text)
    while i < n and i < barrier:
        idx = text.find('<', i)
        if idx < 0 or idx >= barrier:
            break
        if idx in closed_span_by_start:
            i = closed_span_by_start[idx]
            continue
        if idx in open_body_starts:
            barrier = min(barrier, idx)
            break
        # Unmatched '<' — could be a partial tag (e.g. '<fie' awaiting more data)
        # or unrelated literal text. Either way, can't advance past it safely.
        barrier = min(barrier, idx)
        break

    next_safe = max(start_offset, barrier)
    return [positions[k] for k in sorted(positions.keys())], next_safe


def parse_xml(
    text: str,
    allowed_tags: Optional[Set[str]] = None,
    rejected_tags: Optional[Set[str]] = None,
) -> List[XmlOp]:
    """Parse XML operations from a text string.

    See ``_parse_xml_impl`` for the custom algorithm. This entry point
    parses the entire ``text`` and returns ops in document order (with
    final-parse recovery of unclosed body tags). For incrementally-streamed
    buffers, prefer ``parse_xml_streaming``.
    """
    ops, _ = _parse_xml_impl(text, allowed_tags, rejected_tags, start_offset=0, final=True)
    return ops


def parse_xml_streaming(
    text: str,
    *,
    allowed_tags: Optional[Set[str]] = None,
    rejected_tags: Optional[Set[str]] = None,
    start_offset: int = 0,
) -> Tuple[List[XmlOp], int]:
    """Streaming-friendly variant of ``parse_xml`` for append-only buffers.

    Designed for the LLM-streaming hot path where the same buffer is reparsed
    on every chunk. Calling ``parse_xml`` repeatedly on a growing buffer is
    O(N²) overall; this variant takes a ``start_offset`` and parses only the
    suffix, making total work across a stream O(N).

    Args:
        text: The full accumulated buffer.
        allowed_tags: Optional tag whitelist.
        rejected_tags: Optional set populated with tags rejected by the whitelist.
        start_offset: Skip everything before this byte index. Tags that opened
            before ``start_offset`` are NOT re-discovered, so the caller must
            never advance past an unresolved tag — pass back the
            ``next_safe_offset`` returned by the previous call.

    Returns:
        ``(ops, next_safe_offset)`` where ``next_safe_offset`` is the position
        past the last fully-resolved tag, never crossing an unclosed body-tag
        opening or a partial ``<...`` suffix at the buffer tail.
    """
    return _parse_xml_impl(text, allowed_tags, rejected_tags, start_offset)


# ============================================================================
# Line-by-line streaming parser
# ============================================================================

def parse_xml_line(line: str, allowed_tags: Optional[Set[str]] = None) -> Optional[XmlOp]:
    """Parse a single line of XML, returning an XmlOp or None.

    Used for streaming line-by-line parsing (builder). Only handles single-line
    self-closing tags — body tags spanning multiple lines are not supported.
    """
    stripped = line.strip()
    if not stripped or not stripped.startswith('<'):
        return None

    # Try tag with attributes first
    m = _TAG_PATTERN.match(stripped)
    if m:
        tag = m.group(1)
        if allowed_tags and tag not in allowed_tags:
            return None
        return XmlOp(tag=tag, attrs=_parse_attrs(m.group(2)))

    # Try bare tag (no attributes)
    m = _BARE_TAG_PATTERN.match(stripped)
    if m:
        tag = m.group(1)
        if allowed_tags and tag not in allowed_tags:
            return None
        return XmlOp(tag=tag, attrs={})

    return None
