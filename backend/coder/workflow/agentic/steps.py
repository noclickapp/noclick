"""What the builder is doing, op by op: each op it runs and the thing it acts on (a step by its label and app, the
field it sets, the words it searched for), for the builder panel to say ("Added step · Google Calendar") and for
whatever follows a run outside the canvas. Planned before a batch runs, then each op's outcome once it has run, so
nothing reads as done that didn't happen. Words for the ops themselves live with whoever draws them."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..graph_state import GraphState
from ..workflow_xml import XmlOp

# Ops that act on one step, named by their `node` attribute.
_ON_A_STEP = frozenset({
    'field', 'set_credentials', 'update_settings', 'read_config', 'get_output', 'list_outputs', 'run_node',
})
# Ops whose target is words they were given: what they searched for, or what they named.
_SAID = {
    'list_workflows': ('query', 'search'),
    'search_credentials': ('query',),
    'create_workflow': ('name',),
    'create_folder': ('name',),
    'define_variable': ('name',),
    'add_test_run': ('name',),
    'run_test': ('name', 'run'),
    'read': ('topic',),
}


def _first(attrs: Dict[str, str], keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        value = (attrs.get(key) or '').strip()
        if value:
            return value
    return None


def _name(step: Dict[str, Any], label: str, node_type: str) -> None:
    if label:
        step['target'] = label
    if node_type:
        step['node_type'] = node_type


def builder_steps(ops: List[XmlOp], graph: GraphState) -> List[Dict[str, Any]]:
    """One entry per op: ``op``, and where it has them ``target`` (what a person reads), ``node_type`` (the app, for a
    step whose label it doesn't know), ``field``, and an edge's ``ends`` (each by its label, else its app). The names
    the brain gives steps are its own handles, never shown: a step with no label of its own is named by its app."""
    added = {
        op.attrs.get('name', ''): (op.attrs.get('label') or '', op.attrs.get('type') or '')
        for op in ops if op.tag == 'add_node'
    }
    # A step removed and added again under the same handle is, after the batch, the one added.
    replaced = {op.attrs.get('name', '') for op in ops if op.tag == 'remove_node'} & set(added)

    def step_of(ref: str) -> Tuple[str, str]:
        """A step's label (none when it's only the brain's handle for it) and type, by that handle."""
        node = None if ref in replaced else graph.get_node(ref)
        label, node_type = (node.label or '', node.type or '') if node else added.get(ref, ('', ''))
        return ('' if label == ref else label), node_type

    steps: List[Dict[str, Any]] = []
    for op in ops:
        attrs = op.attrs
        step: Dict[str, Any] = {'op': op.tag}
        if op.tag == 'add_node':
            # Named as it says it will be: the step under its handle now may be one it replaces.
            label = attrs.get('label') or ''
            _name(step, '' if label == attrs.get('name') else label, attrs.get('type') or '')
        elif op.tag in ('add_edge', 'remove_edge'):
            ends = []
            for end in ('from', 'to'):
                label, node_type = step_of(attrs.get(end, ''))
                ends.append({'label': label} if label else {'node_type': node_type} if node_type else {})
            if all(end.get('label') for end in ends):
                step['target'] = ' → '.join(end['label'] for end in ends)
            if all(ends):
                step['ends'] = ends
        elif op.tag == 'remove_node':
            # Named as it was before the batch, whatever replaces it.
            node = graph.get_node(attrs.get('name', ''))
            if node:
                _name(step, '' if node.label == node.id else node.label or '', node.type or '')
        elif op.tag in _ON_A_STEP:
            _name(step, *step_of(attrs.get('node') or attrs.get('id') or ''))
            field = attrs.get('name') if op.tag == 'field' else attrs.get('field') if op.tag == 'read_config' else None
            if field:
                step['field'] = field
        elif op.tag in ('query_operations', 'query_schema'):
            if attrs.get('type'):
                step['node_type'] = attrs['type']
        elif op.tag in _SAID:
            said = _first(attrs, _SAID[op.tag])
            if said:
                step['target'] = said
        steps.append(step)
    return steps


# Why an op didn't happen, in a person's words.
NOT_AN_APP = "not an app NoClick has"
NOT_THERE = "that step isn't there"
NOT_JOINED = "those steps can't be connected that way"
NOT_ACCEPTED = "the value wasn't accepted"
NOT_ATTACHED = "the account couldn't be attached"
NOTHING_TO_SET = "it wasn't given anything to set"
NOT_SAVED = "it couldn't be saved"
NOT_RUN = "it couldn't run"
EXITED = "it exited with an error"
_FIELD_REFUSALS = ("Field error: {n}.{f}", "REJECTED {n}.{f}", "PATCH FAILED for {n}.{f}", "Field error: cannot patch {n}.{f}")
# Ops that read a step: they happened when the step is there.
_READS = frozenset({'read_config', 'get_output', 'list_outputs', 'run_node'})


def _word(char: str) -> bool:
    return char.isalnum() or char in '_-'


def _says(line: str, prefix: str) -> bool:
    """Whether ``line`` begins with ``prefix``, never with a longer name that merely starts with it."""
    return line.startswith(prefix) and not (
        len(line) > len(prefix) and _word(prefix[-1]) and _word(line[len(prefix)])
    )


def field_refused(node: str, field: str, results: Iterable[str]) -> bool:
    """Whether a batch's results refused the value it set for ``node``'s ``field``."""
    refused = [r.format(n=node, f=field) for r in _FIELD_REFUSALS]
    return any(_says(line.strip(), prefix) for line in results for prefix in refused)


def _credential_ids(attrs: Dict[str, str]) -> List[str]:
    """The credential ids a ``set_credentials`` names, as the builder reads them."""
    pairs = {k: v for k, v in attrs.items() if k not in ('node', 'id')}
    simplified = attrs.get('id') if attrs.get('node') and not pairs else None
    return [v for v in pairs.values() if v] + ([simplified] if simplified else [])


def _lines_about(op: XmlOp) -> List[Tuple[str, Optional[str], bool]]:
    """The lines a batch reports about ``op``: how each begins, why it says the op didn't happen (None when it did),
    and whether it is the op's last."""
    a = op.attrs
    if op.tag == 'add_node':
        n = a.get('name', '')
        return [(f"Added node '{n}' (", None, True), (f"Node '{n}' already exists, skipped", None, True),
                (f"ERROR: add_node '{n}' skipped", NOT_AN_APP, True)]
    if op.tag in ('add_edge', 'remove_edge'):
        f, t = a.get('from', ''), a.get('to', '')
        if op.tag == 'remove_edge':
            return [(f"Removed edge: {f} → {t}", None, True)]
        if not (f and t):
            return [("ERROR: add_edge skipped", NOT_THERE, True)]
        missing = (f"source node '{f}' does not exist", f"target node '{t}' does not exist",
                   f"source '{f}' was rejected", f"target '{t}' was rejected")
        return [
            (f"Added edge: {f} → {t}", None, True), (f"Added tools edge: {f} now provides agent tools to {t}.", None, True),
            (f"Edge {f} → {t} already exists, skipped", None, True),
            *[(f"ERROR: add_edge {f} → {t} skipped — {m}", NOT_THERE, True) for m in missing],
            (f"ERROR: add_edge {f} → {t} ", NOT_JOINED, True),
        ]
    if op.tag == 'remove_node':
        return [(f"Removed node '{a.get('name', '')}'", None, True)]
    if op.tag == 'field':
        n, f = a.get('node', ''), a.get('name', '')
        return [(f"Field error: node '{n}' not found", NOT_THERE, True),
                *[(r.format(n=n, f=f), NOT_ACCEPTED, True) for r in _FIELD_REFUSALS],
                (f"Set {n}.{f} =", None, True), (f"Patched {n}.{f}", None, True)]
    if op.tag == 'set_credentials':
        n, ids = a.get('node') or a.get('id', ''), _credential_ids(a)
        if not ids:
            return [(f"Credentials error: node '{n}' not found", NOT_THERE, True),
                    ("Credentials error: no credential ID provided", NOT_ATTACHED, True)]
        # Each id it couldn't attach has a line of its own; any it could, one line for them all.
        return [(f"Credentials error: node '{n}' not found", NOT_THERE, True), (f"Set credentials on {n}:", None, True),
                *[(f"Credentials error: node '{n}' — credential {cid} ", NOT_ATTACHED, False) for cid in ids]]
    if op.tag == 'add_sticky_note':
        return [(f"Added sticky note '{a.get('name', '')}' (", None, True)]
    if op.tag == 'define_variable':
        n = (a.get('name') or '').strip()
        if not n:
            return [("ERROR: define_variable requires a 'name'", NOT_ACCEPTED, True)]
        return [(f"Defined variable '{n}'", None, True), (f"ERROR: define_variable: invalid name {n!r}", NOT_ACCEPTED, True)]
    if op.tag == 'add_test_run':
        n, trigger = (a.get('name') or '').strip(), (a.get('trigger') or '').strip()
        return [(f"Added test run '{n}' (", None, True), (f"ERROR: add_test_run — no node '{trigger}'", NOT_THERE, True)]
    if op.tag == 'update_settings':
        n = a.get('node') or a.get('id', '')
        return [(f"Settings error: node '{n}' not found", NOT_THERE, True),
                (f"Settings error: no fields provided for '{n}'", NOTHING_TO_SET, True),
                (f"Settings error on '{n}':", NOT_ACCEPTED, True), (f"Updated settings for '{n}':", None, True)]
    return []


# Why an op that said nothing about itself didn't happen; any other op's step isn't there.
_UNSAID = {
    'set_credentials': NOT_ATTACHED, 'define_variable': NOT_SAVED, 'add_test_run': NOT_SAVED,
    'add_sticky_note': NOT_SAVED, 'bash': NOT_RUN, 'run_test': NOT_RUN,
}
_TEST_RUN_OPENED = "run_test: opened the Test Run screen"


def _command_ran(op: XmlOp, results: str, start: int) -> Tuple[Optional[str], int]:
    """How a ``bash`` op went, read where its report begins in the summary at or after ``start`` (a command can
    span lines, so its report is found in the text, not by line), and where to look for the next one."""
    command = (op.body or '').strip()
    if not command:
        head = "[bash] Error: put the shell command"
    else:
        head = f"[bash {command if len(command) <= 120 else command[:120] + '…'}] "
    at = results.find(head, start)
    if at < 0:
        return NOT_RUN, start
    rest = results[at + len(head):]
    if command and rest.startswith('exit 0') and not rest[6:7].isdigit():
        return None, at + len(head)
    return (EXITED if command and rest.startswith('exit ') else NOT_RUN), at + len(head)


def _reported(results: str) -> List[str]:
    """The lines a batch reported about the changes it made: its graph changes and field overrides."""
    lines: List[str] = []
    for section in (results or '').split('\n\n'):
        head, _, body = section.partition('\n')
        if head in ('Graph changes:', 'Field overrides:'):
            lines += [line.strip() for line in body.splitlines()]
    return lines


def step_outcomes(ops: List[XmlOp], steps: List[Dict[str, Any]], graph: GraphState, results: str) -> List[Dict[str, Any]]:
    """Each planned step once its batch has run: ``ok``, and when it isn't, the ``reason``. Each op is judged by the
    lines the batch reported about it (``results``, its execution summary), each line read for one op only; an op
    that only reads a step happened when the step is there, a command by how it exited, a rehearsal by whether its
    screen opened. A value written and then reverted by the check over its
    whole step (a refusal after the line that set it) wasn't kept."""
    lines = _reported(results)
    claimed = [False] * len(lines)
    judged: List[Tuple[Optional[str], Optional[int]]] = []
    commands_from = 0
    for op in ops:
        if op.tag == 'bash':
            reason, commands_from = _command_ran(op, results or '', commands_from)
            judged.append((reason, None))
            continue
        if op.tag == 'run_test':
            judged.append((None if _TEST_RUN_OPENED in (results or '') else NOT_RUN, None))
            continue
        expected = _lines_about(op)
        reason, at = None, None
        for i, line in enumerate(lines):
            if claimed[i]:
                continue
            match = next((e for e in expected if _says(line, e[0])), None)
            if not match:
                continue
            claimed[i], at = True, i
            expected.remove(match)
            _, reason, last = match
            # Its last line says how it ended; until then, a line about part of it (an account it couldn't
            # attach) stands, and once every part has its line there's no more to read.
            if last or not any(not e[2] for e in expected):
                break
        if at is None and _lines_about(op):
            reason = _UNSAID.get(op.tag, NOT_THERE)
        elif op.tag in _READS and not graph.get_node(op.attrs.get('node', '')):
            reason = NOT_THERE
        judged.append((reason, at))
    # Read once every op has its own lines: a refusal left over came after the values were written, and decides
    # every write of that field before it.
    for k, op in enumerate(ops):
        reason, at = judged[k]
        if op.tag == 'field' and reason is None and at is not None:
            refused = [r.format(n=op.attrs.get('node', ''), f=op.attrs.get('name', '')) for r in _FIELD_REFUSALS]
            if any(not claimed[i] and any(_says(lines[i], p) for p in refused) for i in range(at + 1, len(lines))):
                judged[k] = (NOT_ACCEPTED, at)
    return [
        {**step, 'ok': reason is None, **({'reason': reason} if reason else {})}
        for step, (reason, _) in zip(steps, judged)
    ]
