"""Finding a node type by what a person calls its app or by what they want done: one ranking for the AI builder's
``<find_nodes>``, the workflow MCP server's ``search_operations`` and ``get_available_node_types``, and the
platform's integration catalog (``GET /v1/integrations?q=``).

With some 1,265 node types, a list in registry or alphabetical order put an obscure look-alike first (``box`` found
Arbox before Box, ``sms`` found Mailchimp) and a phrase found nothing. A node type is scored on the query's words:

- each word where it occurs best: the app's name (its type and label), its keywords, its description, or one of its
  operations, weighted by how rare the word is across the catalog (``sms`` says less than ``canva``);
- the query as the app's whole name (``box`` is Box), or one of its words as the app's own (``sharepoint``), ranks
  first by far;
- a node type that covers every word beats one that covers some;
- then, where the deployment says how much people look for each app (``NODE_DEMAND``), the most used among those the
  words fit about as well: Twilio before an SMS app few have heard of for ``send sms``. Without it, fit alone.

What it reads of a node type is its own: its type, its class's description and its operations (``_facts``).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

_PREFIXES = ("automation-", "trigger-", "interface-")
# Words that say nothing about which app: "send me an SMS via ..." is about "send" and "sms".
_STOP = frozenset("""a an the my me our your to of for from in on at by with via using and or i we you it is be this
    that these each every when whenever new please want need can could would should will just some any all""".split())
# Monthly searches assumed for a node type the deployment's demand has none for: NoClick's own steps, which their
# names find, and an integration added since it was measured, most of which are as little known as the median one.
UNMEASURED_DEMAND = 1_000
# How the fields a word occurs in weigh against each other.
_NAME, _KEYWORD, _DESCRIPTION, _OPERATION = 3.0, 1.5, 1.0, 1.0
# The query as an app's whole name, or one of its words as one.
_WHOLE_NAME, _NAMED = 60.0, 12.0
# A word in this many apps' names names a kind of app: it weighs as a keyword.
_KIND_NAMES = 3
# A word of an app's name this rare across the catalog (in under ~1 in 60 node types) names that app.
_OWN_WORD = 4.0


def stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def words(text: Optional[str]) -> List[str]:
    """``text``'s words as the index keeps them: lowercase, singular, without words that name nothing."""
    return [stem(w) for w in re.findall(r"[a-z0-9]+", (text or "").casefold()) if w not in _STOP]


def compact(text: Optional[str]) -> str:
    """A name with only its letters and digits, each word singular: ``Google Sheets`` -> ``googlesheet``."""
    return "".join(stem(w) for w in re.findall(r"[a-z0-9]+", (text or "").casefold()))


@dataclass(frozen=True)
class Operation:
    name: str
    display_name: str
    description: str
    words: FrozenSet[str]
    name_words: FrozenSet[str]  # its name's and display name's alone


@dataclass(frozen=True)
class Entry:
    node_type: str
    slug: str
    label: str
    description: str
    category: Optional[str]
    demand: Optional[int]          # monthly searches; None where the deployment measures none
    names: FrozenSet[str]          # its whole names, compacted: slug, label
    name_words: FrozenSet[str]
    keyword_words: FrozenSet[str]
    description_words: FrozenSet[str]
    operations: Tuple[Operation, ...]


@dataclass(frozen=True)
class Hit:
    entry: Entry
    score: float
    covered: int                   # how many of the query's words it has somewhere
    named: bool                    # the query, or one of its words, is the app's whole name
    operations: Tuple[Operation, ...]  # its operations the query's words fit, the best first
    described: int = 0             # how many of the query's words its name, keywords or description have

    @property
    def node_type(self) -> str:
        return self.entry.node_type


def slug_of(node_type: str) -> str:
    for prefix in _PREFIXES:
        if node_type.startswith(prefix):
            return node_type[len(prefix):]
    return node_type


def _facts(node_type: str) -> Dict[str, object]:
    """What a node type says about itself: its label, a line about it, its keywords and category. Today its class's
    docstring is the only one of these the engine holds, so the label is its type's; per-type facts generated from the
    canvas's definitions (labels like "X", keywords like "CRM") take this function's place."""
    from nodes.core.registry import NODE_REGISTRY

    doc = (NODE_REGISTRY[node_type].__doc__ or "").strip().splitlines()
    return {"label": slug_of(node_type).replace("-", " ").title(), "description": doc[0].strip() if doc else ""}


def knows_demand() -> bool:
    """Whether the deployment says how much people look for each app (``NODE_DEMAND``)."""
    from utils.capabilities import NODE_DEMAND, capability

    return capability(NODE_DEMAND) is not None


def _demand(node_type: str) -> Optional[int]:
    from utils.capabilities import NODE_DEMAND, capability

    lookup = capability(NODE_DEMAND)
    if lookup is None:
        return None
    found = lookup(node_type)
    return UNMEASURED_DEMAND if found is None else int(found)


def _operations(node_type: str) -> Tuple[Operation, ...]:
    from coder.workflow.operation_catalog import get_operations_for_node_type

    out = []
    for op in get_operations_for_node_type(node_type):
        display = op.display_name or op.name.replace("_", " ")
        text = " ".join(filter(None, (op.name.replace("_", " "), display, op.category, op.description)))
        out.append(Operation(op.name, display, op.description or "", frozenset(words(text)),
                             frozenset(words(f"{op.name.replace('_', ' ')} {display}"))))
    return tuple(out)


def entry(node_type: str) -> Entry:
    return _index()[0][node_type]


def _entry(node_type: str) -> Entry:
    facts = _facts(node_type)
    slug = slug_of(node_type)
    label = str(facts.get("label") or slug)
    keywords = " ".join(facts.get("keywords") or ()) + " " + str(facts.get("category") or "").replace("-", " ")
    return Entry(
        node_type=node_type, slug=slug, label=label, description=str(facts.get("description") or ""),
        category=facts.get("category"), demand=_demand(node_type),
        names=frozenset(filter(None, (compact(slug), compact(label)))),
        name_words=frozenset(words(slug.replace("-", " ")) + words(label)),
        keyword_words=frozenset(words(keywords)), description_words=frozenset(words(facts.get("description"))),
        operations=_operations(node_type),
    )


@lru_cache(maxsize=1)
def _index() -> Tuple[Dict[str, Entry], Dict[str, float], FrozenSet[str]]:
    """Every searchable node type's entry; each word's rarity across them (its inverse document frequency); and the
    words several apps' names share, which name a kind of app rather than one (``sms``, ``crm``, ``google``)."""
    from nodes.core.registry import NODE_REGISTRY

    entries = {t: _entry(t) for t in NODE_REGISTRY if not t.startswith("test-")}
    seen: Dict[str, int] = {}
    in_names: Dict[str, int] = {}
    for e in entries.values():
        every = e.name_words | e.keyword_words | e.description_words
        every = every.union(*(op.words for op in e.operations)) if e.operations else every
        for w in every:
            seen[w] = seen.get(w, 0) + 1
        for w in e.name_words:
            in_names[w] = in_names.get(w, 0) + 1
    total = len(entries)
    kinds = frozenset(w for w, n in in_names.items() if n >= _KIND_NAMES)
    return entries, {w: math.log(1 + total / n) for w, n in seen.items()}, kinds


def _rarity(word: str) -> float:
    entries, idf, _ = _index()
    return idf.get(word, math.log(1 + len(entries)))


def _name_holds(e: Entry, query: str) -> float:
    """How far a name holds the query: 1 as its start ("zoom" in ZoomInfo), less inside it ("mail" in Gmail, "close"
    in iClosed, which isn't Close), 0 not at all or for a query too short to tell."""
    if len(query) < 3:
        return 0.0
    return max((1.0 if name.startswith(query) else 0.4 if query in name else 0.0) for name in e.names)


def _score(e: Entry, query_words: Sequence[str], whole: str) -> Optional[Hit]:
    score, covered = 0.0, 0
    named = whole in e.names
    fitting: List[Tuple[float, int, Operation]] = []
    for position, op in enumerate(e.operations):
        fit = sum(_rarity(w) for w in query_words if w in op.words)
        if fit:
            fitting.append((fit, -position, op))
    fitting.sort(key=lambda f: (-f[0], -f[1]))
    best_op = fitting[0][2].words if fitting else frozenset()
    kinds = _index()[2]
    for w in query_words:
        # A word only its operations have weighs by how much of what it does is about it: Gmail's are about email,
        # Twilio's and Supabase's mention it in passing.
        about = sum(w in op.words for op in e.operations) / len(e.operations) if e.operations else 0.0
        weight = (_NAME if w in e.name_words and w not in kinds else _KEYWORD if w in e.name_words | e.keyword_words
                  else _DESCRIPTION if w in e.description_words
                  else _OPERATION * (0.5 + min(about, 1.0)) if w in best_op
                  else _OPERATION * 0.5 if any(w in f[2].words for f in fitting) else 0.0)
        if weight:
            covered += 1
            score += weight * _rarity(w)
        if w in e.names or (w in e.name_words and w not in kinds and len(w) > 3 and _rarity(w) >= _OWN_WORD):
            named = True  # "sharepoint" is Microsoft SharePoint's own; "google" names a kind of app, "upload" an act
            score += _NAMED
    if whole in e.names:
        covered, score = len(query_words), score + _WHOLE_NAME  # "googlesheets" is Google Sheets, word or no word
    elif _name_holds(e, whole):
        # "mail" in Gmail, "box" in Dropbox: a name holding the query, below every name that is it.
        covered, score = len(query_words), score + _NAME * _rarity(whole) * 0.5 * _name_holds(e, whole)
    if not covered:
        return None
    if len(query_words) > 1 and fitting and all(w in fitting[0][2].words for w in query_words):
        # One operation does all it asks, the more nearly it is the query the more: Stripe's create_payment_link
        # for "create payment link" over QuickBooks' create_payment, whose description mentions a link.
        best = fitting[0][2]
        named_by = len(set(query_words) & best.name_words)
        score += fitting[0][0] * named_by * named_by / (len(query_words) * max(len(best.name_words), 1))
    share = covered / max(len(query_words), 1)
    # A fit counts by the order of magnitude of the app's demand: among apps the words fit about as well, the one
    # people look for most, and never an app the words barely fit.
    score = score * share * share * (math.log10(max(e.demand, 10)) if e.demand is not None else 1.0)
    described = sum(w in e.name_words | e.keyword_words | e.description_words for w in query_words)
    return Hit(e, round(score, 3), covered, named, tuple(f[2] for f in fitting), described)


def search(query: str, *, node_types: Optional[Iterable[str]] = None, limit: Optional[int] = None) -> List[Hit]:
    """The node types ``query`` fits, the best first. A query of only stop words fits none. Unscoped, it leaves
    out a retired type (``registry.is_listed``); one ``node_types`` names is still read."""
    from nodes.core.registry import is_listed

    entries = _index()[0]
    query_words = list(dict.fromkeys(words(query)))
    whole = compact(query)
    if not query_words and not whole:
        return []
    pool = ((e for e in entries.values() if is_listed(e.node_type)) if node_types is None
            else (entries[t] for t in node_types if t in entries))
    hits = [h for h in (_score(e, query_words, whole) for e in pool) if h is not None]
    hits.sort(key=lambda h: (-h.score, h.entry.slug))
    return hits[:limit] if limit else hits


def by_popularity(node_types: Iterable[str]) -> List[str]:
    """``node_types``, the most looked-for app first, then by name (by name alone where demand is unknown)."""
    entries = _index()[0]
    known = [t for t in node_types if t in entries]
    return sorted(known, key=lambda t: (-(entries[t].demand or 0), entries[t].slug))


def is_named(query: str, hits: Sequence[Hit]) -> bool:
    """Whether any hit is the app ``query`` names: when none is, an app it names isn't in the catalog, and the hits
    only do what its words say (``close`` finds iClosed and issue trackers, none of them Close)."""
    return any(h.named for h in hits)


def nearest(node_type: str, limit: int = 3) -> List[str]:
    """The node types a mistyped or invented ``node_type`` most likely meant (``automation-sharepoint`` ->
    ``automation-microsoft-sharepoint``), by its words."""
    return [h.node_type for h in search(slug_of(node_type).replace("-", " "), limit=limit)]
