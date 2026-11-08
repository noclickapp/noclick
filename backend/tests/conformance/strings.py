"""Bounded synthetic strings; generation never substitutes for validation."""
from __future__ import annotations

import copy
import re
from re import _constants as c, _parser as parser

from openapi_schema_validator import oas30_format_checker


class PatternError(ValueError):
    """A regex contract needs an exact dialect translation or a curated witness."""


def python_pattern(pattern):
    """Translate only equivalent ECMAScript syntax, preserving the contract.

    Consume escapes as pairs so a literal \\ followed by u/p is never rewritten.
    Unicode properties, surrogate code points and flags without an exact mapping
    deliberately remain contract blockers, rather than having checks removed.
    """
    out, i, in_class = [], 0, False
    while i < len(pattern):
        if pattern[i] == "\\" and i + 1 < len(pattern):
            if pattern.startswith((r"\p{", r"\P{"), i):
                raise PatternError(
                    f"Unsupported contract pattern {pattern!r}: Unicode property escape"
                )
            codepoint = re.match(r"\\u\{([0-9a-fA-F]+)\}", pattern[i:])
            if codepoint:
                number = int(codepoint[1], 16)
                if number > 0xFFFF or 0xD800 <= number <= 0xDFFF:
                    raise PatternError(
                        f"Unsupported contract pattern {pattern!r}: non-BMP/surrogate escape"
                    )
                out.append(r"\u%04x" % number)
                i += len(codepoint[0])
                continue
            if pattern.startswith(r"\k<", i):
                # JS backreferences to an unmatched capture match empty;
                # Python rejects them. A textual rewrite is not equivalent.
                raise PatternError(
                    f"Unsupported contract pattern {pattern!r}: named backreference"
                )
            out.append(pattern[i : i + 2])
            i += 2
            continue
        group = (
            None
            if in_class
            else re.match(r"\(\?<([A-Za-z_][A-Za-z0-9_]*)>", pattern[i:])
        )
        if group:
            out.append(f"(?P<{group[1]}>")
            i += len(group[0])
        else:
            if pattern[i] == "[":
                in_class = True
            elif pattern[i] == "]":
                in_class = False
            out.append(pattern[i])
            i += 1
    translated = "".join(out)
    try:
        re.compile(translated)
    except (re.error, OverflowError) as exc:
        raise PatternError(f"Unsupported contract pattern {pattern!r}: {exc}") from exc
    return translated


def validation_patterns(value, *, schema=False, schema_map=False):
    """An equivalent validator view; leave source schemas and examples intact.

    Only schema keywords are translated. A property named ``pattern`` or an
    example/extension object with that key is data, not a regex contract.
    """
    if isinstance(value, list):
        return [validation_patterns(v, schema=schema) for v in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if schema_map:
            result[key] = validation_patterns(item, schema=True)
        elif schema and key == "pattern" and isinstance(item, str):
            result[key] = python_pattern(item)
        elif (
            key in {"example", "examples", "default", "enum", "const"}
            or key.startswith("x-")
            and key != "x-conformance-witness"
        ):
            result[key] = copy.deepcopy(item)
        elif key in {"schema", "x-conformance-witness"}:
            result[key] = validation_patterns(item, schema=True)
        elif (
            key == "schemas"
            or schema
            and key
            in {
                "properties",
                "patternProperties",
                "$defs",
                "definitions",
                "dependentSchemas",
            }
        ):
            result[key] = validation_patterns(item, schema_map=True)
        elif schema and key in {
            "items",
            "additionalProperties",
            "contains",
            "unevaluatedItems",
            "unevaluatedProperties",
            "propertyNames",
            "not",
            "if",
            "then",
            "else",
            "contentSchema",
            "allOf",
            "oneOf",
            "anyOf",
            "prefixItems",
        }:
            result[key] = validation_patterns(item, schema=True)
        else:
            result[key] = validation_patterns(item)
    return result


FORMATS = {
    "date-time": "2024-01-01T00:00:00Z",
    "date": "2024-01-01",
    "uri": "https://example.test",
    "url": "https://example.test",
    "uri-template": "https://example.test",
    "email": "test@example.com",
    "uuid": "00000000-0000-4000-8000-000000000001",
    "hostname": "example.test",
    "ipv4": "192.0.2.1",
    "byte": "Y29uZm9ybWFuY2U=",
    "binary": "conformance",
}


def regex_values(pattern, minimum, maximum):
    """Small deterministic generator for literals, classes, branches and repeats.

    Explore repeat lengths and alternatives within a fixed work budget. Assertions
    are checked by fullmatch at the caller; unsupported constructs fail closed.
    """
    parsed = parser.parse(pattern)
    limit = min(maximum, max(minimum, parsed.getwidth()[0]) + 128, 4096)
    fuel = 20000

    def category(kind, char):
        positive = {
            c.CATEGORY_DIGIT: char.isdecimal(),
            c.CATEGORY_SPACE: char.isspace(),
            c.CATEGORY_WORD: char.isalnum() or char == "_",
        }
        negative = {
            c.CATEGORY_NOT_DIGIT: c.CATEGORY_DIGIT,
            c.CATEGORY_NOT_SPACE: c.CATEGORY_SPACE,
            c.CATEGORY_NOT_WORD: c.CATEGORY_WORD,
        }
        if kind in negative:
            return not positive[negative[kind]]
        if kind not in positive:
            raise PatternError(
                f"Unsupported contract pattern {pattern!r}: category {kind}"
            )
        return positive[kind]

    def characters(items):
        negated = items[0][0] == c.NEGATE
        items = items[1:] if negated else items
        choices = list("aA01_- ./:@")
        for op, arg in items:
            if op == c.LITERAL:
                choices.append(chr(arg))
            elif op == c.RANGE:
                choices.append(chr(arg[0]))
            elif op != c.CATEGORY:
                raise PatternError(
                    f"Unsupported contract pattern {pattern!r}: class {op}"
                )
        for char in dict.fromkeys(choices):
            matches = any(
                (op == c.LITERAL and ord(char) == arg)
                or (op == c.RANGE and arg[0] <= ord(char) <= arg[1])
                or (op == c.CATEGORY and category(arg, char))
                for op, arg in items
            )
            if matches != negated:
                yield char

    def build(tokens, budget, needed=0):
        nonlocal fuel
        fuel -= 1
        if fuel < 0:
            raise PatternError(
                f"Contract pattern {pattern!r} exceeds synthesis budget; curated witness required"
            )
        low_width, high_width = parser.SubPattern(parsed.state, list(tokens)).getwidth()
        if low_width > budget or high_width < needed:
            return
        if not tokens:
            yield ""
            return
        (op, arg), *tail = tokens
        if op == c.LITERAL:
            heads = [chr(arg)]
        elif op == c.NOT_LITERAL:
            heads = [next(ch for ch in "a01_" if ord(ch) != arg)]
        elif op == c.ANY:
            heads = ["a"]
        elif op == c.IN:
            heads = characters(arg)
        elif op == c.CATEGORY:
            heads = characters([(op, arg)])
        elif op == c.SUBPATTERN:
            heads = build(arg[-1], budget)
        elif op == c.BRANCH:
            heads = (v for branch in arg[1] for v in build(branch, budget))
        elif op in {c.MAX_REPEAT, c.MIN_REPEAT}:
            low, high, child = arg
            width = max(1, child.getwidth()[0])
            high = min(high, budget // width)
            # The outer fullmatch checks anchors and lookarounds too.
            for count in range(low, high + 1):
                if count > 4096:
                    break
                yield from build([*list(child) * count, *tail], budget, needed)
            return
        elif op in {c.AT, c.ASSERT, c.ASSERT_NOT}:
            heads = [""]
        else:
            raise PatternError(
                f"Unsupported contract pattern {pattern!r}: synthesis opcode {op}"
            )
        for head in heads:
            if len(head) <= budget:
                for rest in build(tail, budget - len(head), max(0, needed - len(head))):
                    yield head + rest

    if limit >= minimum:
        yield from build(list(parsed), limit, minimum)


def string_sample(schema, *, candidates=None):
    minimum = schema.get("minLength", 0)
    maximum = schema.get("maxLength", max(4096, minimum))
    pattern = python_pattern(schema["pattern"]) if "pattern" in schema else None
    fmt = schema.get("format")

    def valid(value):
        return (
            minimum <= len(value) <= maximum
            and (pattern is None or re.fullmatch(pattern, value) is not None)
            and (
                fmt not in FORMATS
                or oas30_format_checker.conforms(value, "uri" if fmt == "url" else fmt)
            )
        )

    if candidates is not None:
        for value in candidates:
            value += " " * max(0, minimum - len(value))
            if valid(value):
                return value
        raise PatternError(
            f"Cannot synthesize encoded string contract {schema!r}; curated witness required"
        )
    candidates = [FORMATS[fmt]] if fmt in FORMATS else []
    if fmt in {"uri", "url", "uri-template"}:
        candidates.append("https://example.test/" + "a" * max(0, minimum - 21))
    elif fmt == "email":
        candidates.append("a" * max(1, minimum - 12) + "@example.com")
    if pattern is not None:
        # Preserve existing literal-path witnesses when they already fullmatch.
        candidates.append(
            pattern.removeprefix("^").removesuffix("$").replace("[^/]+", "1")
        )
        # Format witnesses are useful for email/URL patterns with lookarounds.
        candidates.extend(FORMATS.values())
    else:
        candidates.append("1" * min(maximum, max(1, minimum)))
    for value in candidates:
        if valid(value):
            return value
    if pattern is not None:
        try:
            for value in regex_values(pattern, minimum, maximum):
                if valid(value):
                    return value
        except RecursionError as exc:
            raise PatternError(
                f"Contract pattern {pattern!r} exceeds synthesis depth; curated witness required"
            ) from exc
    raise PatternError(
        f"Cannot synthesize string contract {schema!r}; curated witness required"
    )


def config_shapes(value):
    """Use explicit node field metadata; never infer provider IDs from names."""
    if isinstance(value, list):
        return [config_shapes(v) for v in value]
    if not isinstance(value, dict):
        return value
    shaped = {
        key: {name: config_shapes(sub) for name, sub in item.items()}
        if key in {"properties", "$defs", "definitions"}
        else copy.deepcopy(item)
        if key in {"default", "enum", "const", "example", "examples"}
        else config_shapes(item)
        for key, item in value.items()
    }
    widget = value.get("ui:widget")
    if widget in {"url", "email", "date", "datetime", "date-time", "media_upload"}:
        shaped.setdefault(
            "format",
            {"url": "uri", "media_upload": "uri", "datetime": "date-time"}.get(
                widget, widget
            ),
        )
    if value.get("x-code-language") == "json" or value.get("format") == "json":
        shaped.setdefault("contentMediaType", "application/json")
    if any(key in shaped for key in ("pattern", "format", "contentMediaType")):
        shaped.pop("default", None)
    return shaped
