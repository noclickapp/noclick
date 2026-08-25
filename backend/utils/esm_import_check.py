"""
Static import/export resolver for interface-html-react components.

Verifies that every NAMED import in generated JSX actually exists as an export of
the real esm.sh module the runtime will load — WITHOUT executing any package code.
It catches the class of runtime failure where the model imports a symbol the served
(latest) package version doesn't provide — e.g. `import { Github } from 'lucide-react'`
after lucide removed its brand icons in 1.x — so node drafter can self-correct before the
component ever ships to the iframe.

Security: fetches module TEXT only (never executes it), locked to the esm.sh host,
size- and time-capped, no credentials. The only untrusted input is a package name;
fetching text for a bogus/hallucinated name just 404s (fail-open).

Fail-open by design: a package whose full export set we cannot CONFIDENTLY resolve
(fetch failure, unresolved `export *` chain, parse doubt) is treated as satisfied.
A false positive would block a valid component — strictly worse than today — so the
checker only ever flags a named import it can PROVE is absent. Default and namespace
imports are never checked (esm.sh synthesizes defaults; namespaces bind everything).
"""

import asyncio
import difflib
import logging
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

ESM_HOST = "esm.sh"
_ESM_ORIGIN = "https://esm.sh"
_EXTERNAL = "react,react-dom"

# Specifiers never resolved over the network: relative/absolute paths, the React
# singleton, the data-URI SDK, and the SDK's dynamic socket.io dep. Mirrors the
# canonical import-map entries in jsx_transpiler.build_import_map.
_SKIP_EXACT = {"react", "react-dom", "react/jsx-runtime", "@noclick/sdk", "socket.io-client"}

_MAX_MODULE_BYTES = 12 * 1024 * 1024
_FETCH_TIMEOUT_S = 8.0
_TOTAL_BUDGET_S = 20.0
_MAX_STAR_DEPTH = 5
_MAX_MISSING_REPORTED = 12
_MAX_AVAILABLE_LISTED = 30
_CACHE_MAX = 2048

# Text or None (None = any failure: non-200, off-host, too big, timeout, exception).
Fetcher = Callable[[str], Awaitable[Optional[str]]]

# Process-lifetime cache keyed by resolved esm.sh URL. Export sets are stable per
# versioned URL; the unpinned entry URL can drift when a package publishes a new
# latest, which is acceptable at process scope (worker processes recycle frequently).
_EXPORT_CACHE: "Dict[str, Optional[ExportInfo]]" = {}


@dataclass
class _ImportUsage:
    named: Set[str] = field(default_factory=set)  # imported export names (source side of `as`)
    default: bool = False
    namespace: bool = False


@dataclass
class ExportInfo:
    names: Set[str]
    has_default: bool


# ── Parsing ──────────────────────────────────────────────────────────────────

# Line-anchored so a string/comment containing "import ... from" doesn't match a
# real statement (real ESM imports are top-level, at line start). The clause forbids
# quotes and `;` so it can't bridge a bare `import '…'` (no `from`) into a later
# line's `from`; braces may still span lines.
_IMPORT_RE = re.compile(
    r"^[ \t]*import\s+(?P<clause>[^;'\"]*?)\s+from\s*['\"](?P<spec>[^'\"]+)['\"]",
    re.MULTILINE,
)
_BRACE_RE = re.compile(r"\{([\s\S]*?)\}")

# Export forms in an esm.sh module. Deliberately GENEROUS: over-collecting an
# export name only causes a MISS (fail-open); under-collecting would false-flag a
# valid import, so every form is covered.
_EXPORT_BRACE_RE = re.compile(r"export\s*\{([^}]*)\}")            # export { a, b as c } [from '…']
_EXPORT_STAR_RE = re.compile(r"export\s*\*\s*from\s*['\"]([^'\"]+)['\"]")  # export * from '…'
_EXPORT_DECL_RE = re.compile(
    r"export\s+(?:async\s+)?(?:function\s*\*?|class|const|let|var)\s+([A-Za-z_$][\w$]*)"
)
_EXPORT_DEFAULT_RE = re.compile(r"export\s+default\b")


def _package_of(spec: str) -> str:
    """Collapse a specifier to its package name for skip checks (subpaths kept for fetch)."""
    if spec.startswith("@"):
        return "/".join(spec.split("/")[:2])
    return spec.split("/")[0]


def _should_resolve(spec: str) -> bool:
    if spec.startswith((".", "/", "http:", "https:", "data:")):
        return False
    if spec in _SKIP_EXACT or _package_of(spec) in _SKIP_EXACT:
        return False
    return True


def parse_imports(source: str) -> Dict[str, _ImportUsage]:
    """Extract {specifier -> usage} from JSX/ESM source. Merges repeated imports."""
    out: Dict[str, _ImportUsage] = {}
    for m in _IMPORT_RE.finditer(source):
        spec = m.group("spec")
        clause = m.group("clause")
        usage = out.setdefault(spec, _ImportUsage())
        brace = _BRACE_RE.search(clause)
        if brace:
            for part in brace.group(1).split(","):
                part = part.strip()
                if not part:
                    continue
                # `a as b` imports the export named `a` (b is the local alias).
                name = re.split(r"\s+as\s+", part)[0].strip()
                if name and name != "default":
                    usage.named.add(name)
        # Detect default/namespace for completeness (not checked).
        head = clause[: brace.start()] if brace else clause
        if re.search(r"\*\s+as\s+", head):
            usage.namespace = True
        elif re.match(r"\s*[A-Za-z_$][\w$]*", head):
            usage.default = True
    return out


def parse_exports(text: str) -> Tuple[Set[str], bool, List[str]]:
    """Return (export names, has_default, `export *` re-export specs) for a module."""
    names: Set[str] = set()
    has_default = False
    stars = [m.group(1) for m in _EXPORT_STAR_RE.finditer(text)]
    for m in _EXPORT_BRACE_RE.finditer(text):
        for part in m.group(1).split(","):
            part = part.strip()
            if not part:
                continue
            toks = re.split(r"\s+as\s+", part)
            exported = toks[-1].strip()
            if exported == "default":
                has_default = True
            elif exported:
                names.add(exported)
    for m in _EXPORT_DECL_RE.finditer(text):
        names.add(m.group(1))
    if _EXPORT_DEFAULT_RE.search(text):
        has_default = True
    return names, has_default, stars


# ── Resolution ───────────────────────────────────────────────────────────────

def _entry_url(spec: str) -> str:
    return f"{_ESM_ORIGIN}/{spec}?external={_EXTERNAL}&bundle"


def _to_esm_url(ref: str) -> Optional[str]:
    """Resolve a `export * from` ref (relative path or absolute URL) to an esm.sh
    URL, or None if it points off-host (never fetched)."""
    url = ref if ref.startswith(("http://", "https://")) else urljoin(_ESM_ORIGIN + "/", ref.lstrip("/"))
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != ESM_HOST:
        return None
    return url


async def _resolve_url(
    url: str, fetch: Fetcher, cache: Dict[str, Optional[ExportInfo]],
    seen: Set[str], depth: int,
) -> Optional[ExportInfo]:
    if url in cache:
        return cache[url]
    if url in seen or depth > _MAX_STAR_DEPTH:
        return None  # cycle or too deep → export set unknown → fail-open
    seen.add(url)

    text = await fetch(url)
    if text is None:
        return None  # fetch failed → unknown

    names, has_default, stars = parse_exports(text)
    for star_ref in stars:
        star_url = _to_esm_url(star_ref)
        sub = await _resolve_url(star_url, fetch, cache, seen, depth + 1) if star_url else None
        if sub is None:
            # An unresolved `export *` means we can't know the FULL set → must not
            # flag any import against a partial set. Fail-open for this module.
            _cache_put(cache, url, None)
            return None
        names |= sub.names  # `export *` re-exports names only, never default
    info = ExportInfo(names=names, has_default=has_default)
    _cache_put(cache, url, info)
    return info


def _cache_put(cache: Dict[str, Optional[ExportInfo]], url: str, val: Optional[ExportInfo]) -> None:
    if cache is _EXPORT_CACHE and len(cache) >= _CACHE_MAX:
        cache.clear()
    cache[url] = val


# ── Default (network) fetcher ────────────────────────────────────────────────

async def _default_fetch(url: str) -> Optional[str]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != ESM_HOST:
        logger.warning("esm_import_check: refusing non-esm.sh URL %s", url)
        return None
    try:
        import httpx
    except Exception:
        return None
    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_S, follow_redirects=True) as client:
            async with client.stream(
                "GET", url, headers={"accept": "application/javascript, text/javascript, */*"}
            ) as resp:
                if resp.status_code != 200:
                    return None
                if resp.url.host != ESM_HOST:  # redirected off esm.sh → refuse
                    return None
                chunks: List[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > _MAX_MODULE_BYTES:
                        return None
                    chunks.append(chunk)
                return b"".join(chunks).decode("utf-8", "replace")
    except Exception as e:
        logger.info("esm_import_check: fetch failed for %s: %s", url, e)
        return None


# ── Public entry ─────────────────────────────────────────────────────────────

async def check_jsx_imports(
    jsx_source: str,
    *,
    fetch: Optional[Fetcher] = None,
    cache: Optional[Dict[str, Optional[ExportInfo]]] = None,
) -> Optional[str]:
    """Return a drafter-retry-ready error string naming named imports that don't exist
    in their resolved esm.sh module, or None if everything resolves (or can't be
    confidently checked). Never raises — any failure is fail-open (returns None)."""
    fetch = fetch or _default_fetch
    cache = _EXPORT_CACHE if cache is None else cache
    try:
        return await asyncio.wait_for(_check(jsx_source, fetch, cache), _TOTAL_BUDGET_S)
    except asyncio.TimeoutError:
        logger.info("esm_import_check: total budget exceeded — skipping (fail-open)")
        return None
    except Exception:
        logger.exception("esm_import_check: unexpected error — skipping (fail-open)")
        return None


async def _check(
    jsx_source: str, fetch: Fetcher, cache: Dict[str, Optional[ExportInfo]]
) -> Optional[str]:
    targets = {
        spec: usage
        for spec, usage in parse_imports(jsx_source).items()
        if usage.named and _should_resolve(spec)
    }
    if not targets:
        return None

    async def resolve(spec: str) -> Optional[ExportInfo]:
        return await _resolve_url(_entry_url(spec), fetch, cache, set(), 0)

    infos = await asyncio.gather(*(resolve(s) for s in targets))

    problems: List[Tuple[str, List[str], Set[str]]] = []
    for (spec, usage), info in zip(targets.items(), infos):
        if info is None:
            continue  # unknown export set → fail-open
        missing = sorted(n for n in usage.named if n not in info.names)
        if missing:
            problems.append((spec, missing, info.names))
    if not problems:
        return None
    return _format_error(problems)


def _format_error(problems: List[Tuple[str, List[str], Set[str]]]) -> str:
    lines = [
        "Some imports reference symbols that the package does not export. The runtime "
        "loads the LATEST version of each package from esm.sh, so an export you expect "
        "may have been renamed or removed. Fix these:",
    ]
    for spec, missing, available in problems:
        for name in missing[:_MAX_MISSING_REPORTED]:
            close = difflib.get_close_matches(name, available, n=3, cutoff=0.7)
            hint = f" Did you mean: {', '.join(close)}?" if close else ""
            lines.append(f"- '{spec}' has no export named '{name}'.{hint}")
        if spec == "lucide-react":
            lines.append(
                "  Note: lucide-react removed brand/logo icons (Github, Twitter, Linkedin, "
                "etc.). Use an inline SVG for brand logos, or a non-brand icon."
            )
        sample = ", ".join(sorted(available)[:_MAX_AVAILABLE_LISTED])
        if sample:
            lines.append(f"  Available exports of '{spec}' include: {sample}.")
    lines.append("Re-output the corrected component using only exports that exist.")
    return "\n".join(lines)
