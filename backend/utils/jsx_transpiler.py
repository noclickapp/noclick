"""
JSX Transpiler for dynamic component rendering.

Provides server-side JSX → JS transpilation using Sucrase (bundled for QuickJS),
import map generation for browser ESM resolution, and srcdoc assembly for
iframe rendering.

For diff/patch application on JSX source, use the simplified unified diff patch
system in ``coder.workflow.patch_utils.apply_patch``.

Usage:
    from utils.jsx_transpiler import transpile_jsx, build_import_map, build_srcdoc

    # Transpile JSX source to browser-ready JS
    result = transpile_jsx(jsx_source)
    if result.success:
        import_map = build_import_map(result.code)
        html = build_srcdoc(result.code, import_map)

    # Apply an LLM-generated patch to JSX source
    from coder.workflow.patch_utils import apply_patch
    new_source = apply_patch(current_source, patch_text)
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Re-export apply_patch for convenience — the canonical diff/patch system
# lives in patch_utils and uses simplified unified diff format with fuzzy matching.
from coder.workflow.patch_utils import apply_patch  # noqa: F401

logger = logging.getLogger(__name__)

# --- Constants ---

ESM_SH = "https://esm.sh"
REACT_VERSION = "19"
EXTERNAL = "react,react-dom"
TAILWIND_CDN = "https://cdn.tailwindcss.com"

# Packages handled as canonical import map entries (not auto-detected from source)
BUILTIN_SPECIFIERS = frozenset({"react", "react-dom", "@noclick/sdk"})

# --- Bundle management ---

_sucrase_bundle: Optional[str] = None
_sdk_bundle: Optional[str] = None


def _load_sucrase_bundle() -> str:
    """Load the bundled Sucrase JS (lazy, cached)."""
    global _sucrase_bundle
    if _sucrase_bundle is None:
        bundle_path = Path(__file__).parent / "sucrase_bundle.js"
        _sucrase_bundle = bundle_path.read_text()
    return _sucrase_bundle


def _load_sdk_bundle() -> str:
    """Load the built @noclick/sdk ES module (lazy, cached)."""
    global _sdk_bundle
    if _sdk_bundle is None:
        # Try local dev path first (repo root / sdk / typescript / dist)
        sdk_path = Path(__file__).parent.parent.parent / "sdk" / "typescript" / "dist" / "sdk.esm.js"
        if not sdk_path.exists():
            # container deployment: mounted at /root/sdk/typescript/dist/
            sdk_path = Path("/root/sdk/typescript/dist/sdk.esm.js")
        _sdk_bundle = sdk_path.read_text()
    return _sdk_bundle


# --- Result types ---


@dataclass
class TranspileResult:
    success: bool
    code: str = ""
    error: str = ""
    elapsed_ms: float = 0.0


@dataclass
class BuildResult:
    """Full pipeline result: transpile + import map + srcdoc."""
    success: bool
    code: str = ""
    import_map: dict = field(default_factory=dict)
    srcdoc: str = ""
    error: str = ""
    timing: dict = field(default_factory=dict)


# --- Transpilation ---


# --- Host-mount transform ---
#
# Lets interface-html-react accept BOTH shapes without a builder-prompt change:
#   1. self-mounting code (the prompt's contract — it calls
#      ReactDOM.createRoot(...).render(...) itself) → returned UNCHANGED, so all
#      existing/published/builder-generated components are byte-identical; and
#   2. Claude-Artifacts-style code that only `export default`s a component →
#      its default export is mounted into #root for it.
# Mirrors the frontend `applyHostMount` in `useClientTranspile.ts` — keep in sync.

# Self-mount detector. Importing `react-dom/client` is the reliable tell: every
# self-mounting component imports it (even when `createRoot` is aliased), the
# Artifacts shape never does, and the appended bootstrap imports it too — which
# makes apply_host_mount idempotent. `createRoot(`/`ReactDOM.render(` also catch
# the legacy `react-dom` API. A three.js `renderer.render(...)` matches none of
# these, so it is correctly host-mounted.
_REACT_MOUNT_RE = re.compile(
    # The react-dom/client import is the reliable self-mount tell: every working
    # React 18/19 mount imports it (createRoot lives ONLY there), the Artifacts
    # shape never does, and the bootstrap imports it too (→ idempotent).
    # `ReactDOM.render` also catches the legacy API. We deliberately do NOT match a
    # bare `createRoot(` — it misfires on object methods / method calls, and real
    # createRoot always carries the react-dom/client import anyway.
    r"\bReactDOM\s*\.\s*render\s*\(|react-dom/client"
)
# Locate the default export. Known limitation: a literal `export default` at a
# line start INSIDE a template literal/string would be matched first; the result
# is a graceful error hint, not a crash. A full fix needs es-module-lexer (FE) /
# an AST (BE) — tracked as future hardening.
_EXPORT_DEFAULT_NAMED_RE = re.compile(
    r"(?m)^\s*export\s+default\s+(?:function|class)\s+([A-Za-z_$][\w$]*)"
)
_EXPORT_BRACE_DEFAULT_RE = re.compile(
    r"(?m)^\s*export\s*\{\s*([A-Za-z_$][\w$]*)\s+as\s+default\s*\}\s*;?"
)
_EXPORT_DEFAULT_RE = re.compile(r"(?m)^\s*export\s+default\s+")

# Appended to non-self-mounting code. Mounts the captured default export into
# #root, guarded so it no-ops if something already mounted (belt-and-suspenders
# for a self-mount the detector missed). The guard checks `childElementCount`
# only when it's a real number, so it proceeds (and exercises the component)
# under the QuickJS validator stub, where it's a Proxy. Synchronous so the
# validator actually renders the component and catches its errors.
_HOST_MOUNT_BOOTSTRAP = """
import { createElement as __ncCreateElement } from 'react';
import { createRoot as __ncCreateRoot } from 'react-dom/client';
(function () {
  var el = (typeof document !== 'undefined' && document.getElementById) ? document.getElementById('root') : null;
  if (!el) return;
  var n = el.childElementCount;
  if (typeof n === 'number' && n > 0) return;
  var comp = (typeof __ncDefault !== 'undefined') ? __ncDefault : null;
  var ok = typeof comp === 'function' || (comp && typeof comp === 'object' && comp.$$typeof);
  if (ok) {
    __ncCreateRoot(el).render(__ncCreateElement(comp));
  } else {
    el.innerHTML = '<div style="font-family:system-ui,sans-serif;color:#a1a1aa;padding:1.5rem;font-size:13px;line-height:1.6">This React code does not render anything. Export your component with <code>export default</code> so it can be mounted.</div>';
  }
})();
"""


def apply_host_mount(jsx_source: str) -> str:
    """Mount a component's default export when the code doesn't mount itself.

    Returns ``jsx_source`` UNCHANGED when it already calls
    ``createRoot()``/``ReactDOM.render()`` (existing/published/builder code).
    Otherwise captures its ``export default`` as a local and appends an
    idempotent, #root-empty-guarded mount. Idempotent: a second pass sees the
    injected ``createRoot(`` and returns unchanged. Mirror of the frontend
    ``applyHostMount`` — keep the two in sync.
    """
    if not jsx_source or not jsx_source.strip():
        return jsx_source
    if _REACT_MOUNT_RE.search(jsx_source):
        return jsx_source

    named = _EXPORT_DEFAULT_NAMED_RE.search(jsx_source)
    if named:
        # Keep the hoisted declaration in module scope; capture it by name.
        code = _EXPORT_DEFAULT_RE.sub("", jsx_source, count=1)
        code += f"\nconst __ncDefault = {named.group(1)};"
    else:
        brace = _EXPORT_BRACE_DEFAULT_RE.search(jsx_source)
        if brace:
            code = jsx_source.replace(brace.group(0), "", 1)
            code += f"\nconst __ncDefault = {brace.group(1)};"
        elif _EXPORT_DEFAULT_RE.search(jsx_source):
            code = _EXPORT_DEFAULT_RE.sub("const __ncDefault = ", jsx_source, count=1)
        else:
            # No default export and no self-mount: still append the bootstrap so
            # the user gets the hint instead of a silent blank.
            code = jsx_source
    return code + _HOST_MOUNT_BOOTSTRAP


def transpile_jsx(jsx_source: str) -> TranspileResult:
    """
    Transpile JSX/TSX source to plain JS using Sucrase via QuickJS.

    Converts JSX elements to React.createElement calls (automatic runtime)
    and strips TypeScript type annotations. Import statements are preserved —
    they resolve via the browser import map at runtime.

    Args:
        jsx_source: JSX/TSX source code string.

    Returns:
        TranspileResult with success/code or error.
    """
    import quickjs

    start = time.perf_counter()
    # Host-mount non-self-mounting (Artifacts-style) code before transpiling, so
    # execute AND publish (both call this) accept the default-export shape.
    jsx_source = apply_host_mount(jsx_source)
    try:
        ctx = quickjs.Context()
        ctx.set_memory_limit(50 * 1024 * 1024)  # 50MB — Sucrase is ~300KB
        ctx.set_max_stack_size(2 * 1024 * 1024)  # 2MB stack — default is too small for deeply nested JSX

        # Load Sucrase
        bundle = _load_sucrase_bundle()
        ctx.eval(bundle)

        # Call transform
        source_json = json.dumps(jsx_source)
        result_json = ctx.eval(
            f"JSON.stringify(sucraseTransform({source_json}, {{"
            f'  transforms: ["jsx", "typescript"],'
            f'  jsxRuntime: "automatic",'
            f'  jsxImportSource: "react",'
            f"  production: true"
            f"}}))"
        )
        parsed = json.loads(result_json)
        elapsed = (time.perf_counter() - start) * 1000
        return TranspileResult(success=True, code=parsed["code"], elapsed_ms=elapsed)

    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        error_msg = str(e)
        logger.warning(f"[JSXTranspiler] Transpile error: {error_msg}")
        return TranspileResult(success=False, error=error_msg, elapsed_ms=elapsed)


# --- Runtime validation ---

# Minimal browser stub for QuickJS — Proxy-based so any property access returns
# another proxy instead of throwing. Enough to survive React's first render cycle.
_BROWSER_STUB = """
// Proxy that returns itself for any property access or function call
function _stub() {
  return new Proxy(function(){}, {
    get: function(t, p) {
      if (p === Symbol.toPrimitive) return function() { return ''; };
      if (p === 'then') return undefined;  // not a Promise
      if (p === 'length') return 0;
      if (p === Symbol.iterator) return function() { return { next: function() { return {done:true}; } }; };
      return _stub();
    },
    apply: function() { return _stub(); },
    construct: function() { return _stub(); },
  });
}

// ── React state simulation ──────────────────────────────────────
// Tracks useState slots across two render passes:
//   Pass 1: returns initial values, records setState calls
//   Second render: returns updated values (what setState was called with)
var _stateSlots = [];     // [{value, updated, updatedValue}]
var _stateIndex = 0;      // current slot pointer (reset between renders)
var _effectCallbacks = []; // useEffect callbacks to run after render
var _renderPass = 1;       // 1 = initial, 2 = re-render with updated state
var _componentFn = null;   // captured App component for re-render
var window = _stub();
var document = new Proxy({}, {
  get: function(t, p) {
    if (p === 'getElementById') return function() { return _stub(); };
    if (p === 'createElement') return function(tag) {
      return _stub();
    };
    if (p === 'createTextNode') return function() { return _stub(); };
    if (p === 'head') return _stub();
    if (p === 'body') return _stub();
    return _stub();
  }
});
var navigator = _stub();
var location = _stub();
var console = { log: function(){}, error: function(){}, warn: function(){}, info: function(){}, debug: function(){} };
var setTimeout = function(fn) { fn(); };
var clearTimeout = function(){};
var setInterval = function(){};
var clearInterval = function(){};
var requestAnimationFrame = function(fn) { fn(0); return 0; };
var cancelAnimationFrame = function(){};
var fetch = function() { return _stub(); };
var HTMLElement = function(){};
var Event = function(){};
var CustomEvent = function(){};
var MutationObserver = function(){ return { observe: function(){}, disconnect: function(){} }; };
var ResizeObserver = MutationObserver;
var IntersectionObserver = MutationObserver;
var localStorage = { getItem: function(){ return null; }, setItem: function(){}, removeItem: function(){} };
var sessionStorage = localStorage;
var matchMedia = function() { return _stub(); };
var self = window;

// require() stub for CommonJS imports (Sucrase converts ES imports to require())
var _modules = {
  'react': {
    createElement: function(type, props) {
      // Mirror jsx/jsxs so a component mounted via createElement(Comp) (e.g. the
      // host-mount bootstrap) is exercised by render(), not just <Comp/> JSX.
      if (typeof type === 'function') {
        if (_componentFn) return type(props || {});
        return { __ncComponent: type, __ncProps: props || {} };
      }
      return {};
    },
    useState: function(init) {
      var idx = _stateIndex++;
      if (_renderPass === 1) {
        // First render: create slot with initial value
        _stateSlots[idx] = { value: init, updated: false, updatedValue: undefined };
        var setter = function(v) {
          // Record the update — it will be applied in the second render
          var slot = _stateSlots[idx];
          slot.updated = true;
          slot.updatedValue = (typeof v === 'function') ? v(slot.value) : v;
          slot.value = slot.updatedValue;
        };
        return [init, setter];
      } else {
        // Second render: return updated value if setState was called.
        // A missing slot is a component that newly mounted in the second render (a
        // state update switched a conditional branch, e.g. loading ->
        // content). Its hooks are fresh mounts — allocate like pass 1
        // instead of crashing on undefined (legal React: hooks rules are
        // per-component, but the slot array is global to the harness).
        var slot = _stateSlots[idx];
        if (!slot) {
          slot = _stateSlots[idx] = { value: init, updated: false, updatedValue: undefined };
        }
        var val = slot.updated ? slot.updatedValue : slot.value;
        return [val, function(v) {
          slot.updated = true;
          slot.updatedValue = (typeof v === 'function') ? v(val) : v;
        }];
      }
    },
    useEffect: function(fn) { _effectCallbacks.push(fn); },
    useCallback: function(f) { return f; },
    useMemo: function(f) { return f(); },
    useRef: function(v) { return {current: v}; },
    useContext: function() { return {}; },
    useReducer: function(r, init) { return [init, function(){}]; },
    useLayoutEffect: function(fn) { _effectCallbacks.push(fn); },
    createContext: function() { return { Provider: function(){} }; },
    forwardRef: function(c) { return c; },
    memo: function(c) { return c; },
    Fragment: 'Fragment',
    Suspense: function(){},
    lazy: function(f) { return function(){}; },
    startTransition: function(f) { f(); },
    useTransition: function() { return [false, function(f){f();}]; },
    useId: function() { return 'id'; },
    Children: { map: function(c,f){ return []; }, forEach: function(){}, count: function(){return 0;}, toArray: function(){return [];} },
    cloneElement: function(el){ return el; },
    isValidElement: function(){ return true; },
    __esModule: true, default: null
  },
  'react/jsx-runtime': {
    jsx: function(type, props) {
      if (typeof type === 'function') {
        // Nested component calls — execute them inline during render
        if (_componentFn) return type(props || {});
        // Top-level component — capture for render()
        return { __ncComponent: type, __ncProps: props || {} };
      }
      return {};
    },
    jsxs: function(type, props) {
      if (typeof type === 'function') {
        if (_componentFn) return type(props || {});
        return { __ncComponent: type, __ncProps: props || {} };
      }
      return {};
    },
    Fragment: 'Fragment'
  },
  'react/jsx-dev-runtime': {
    jsxDEV: function() { return {}; },
    Fragment: 'Fragment'
  },
  'react-dom/client': {
    createRoot: function() {
      return {
        render: function(element) {
          // Extract component function from the jsx() capture
          var fn = element && element.__ncComponent;
          var props = element && element.__ncProps || {};
          if (!fn) return;
          _componentFn = fn;

          // Pass 1: initial render
          _renderPass = 1;
          _stateIndex = 0;
          _effectCallbacks = [];
          fn(props);

          // Run effects synchronously (simulates useEffect after mount)
          var effects = _effectCallbacks.slice();
          _effectCallbacks = [];
          for (var i = 0; i < effects.length; i++) {
            effects[i]();
          }

          // Check if any state was updated by effects
          var hasUpdates = _stateSlots.some(function(s) { return s.updated; });
          if (hasUpdates) {
            // Second render: re-render with updated state values
            // Build a diagnostic of what changed for better error messages
            var _stateChanges = [];
            for (var si = 0; si < _stateSlots.length; si++) {
              var sl = _stateSlots[si];
              if (sl.updated) {
                var fromType = Array.isArray(sl.value) ? 'array' : (sl.value && sl.value._type) || typeof sl.value;
                var toType = Array.isArray(sl.updatedValue) ? 'array' : (sl.updatedValue && sl.updatedValue._type) || typeof sl.updatedValue;
                try { var fromStr = JSON.stringify(sl.value); } catch(e) { var fromStr = String(sl.value); }
                try { var toStr = JSON.stringify(sl.updatedValue); } catch(e) { var toStr = String(sl.updatedValue); }
                if (fromStr && fromStr.length > 40) fromStr = fromStr.substring(0, 40) + '...';
                if (toStr && toStr.length > 40) toStr = toStr.substring(0, 40) + '...';
                _stateChanges.push('useState(' + fromType + ') was set to ' + toType + ': ' + toStr);
              }
            }
            try {
              _renderPass = 2;
              _stateIndex = 0;
              _effectCallbacks = [];
              fn(props);  // This is where bugs like .map() on Promise surface
            } catch(e) {
              // Rethrow with context about what state changed
              throw new Error('Runtime error after state update: ' + e.message + '. State changes: ' + _stateChanges.join('; ') + '. This usually means a useEffect set state to an unexpected type (e.g. storing a Promise instead of awaiting it with .then()). Fix: use state.get(key).then(val => setState(val)) instead of setState(state.get(key)).');
            }
          }
        },
        unmount: function(){}
      };
    },
    __esModule: true, default: null
  },
  'react-dom': {
    createPortal: function() { return {}; },
    flushSync: function(f) { f(); },
    __esModule: true, default: null
  },
  '@noclick/sdk': (function() {
    // Helpers for stubbing async SDK methods
    var _p = function(v) { return { _type:'Promise', then:function(fn){fn(v);return _p(v)}, catch:function(){return _p(v)} }; };
    var _void = function() { return _p(undefined); };
    return {
      // state module
      state: {
        get: function() { return _p(null); },
        set: _void, del: _void, update: _void,
        onChange: function() { return function(){}; },
        keys: function() { return _p([]); },
        subscribe: function() { return function(){}; },
      },
      // nodes module
      nodes: {
        getOutput: function() { return _p(null); },
        getConfig: function() { return _p({}); },
        setConfig: _void,
        list: function() { return _p([]); },
      },
      // execution module
      execution: {
        runNodesAndGetOutput: function() { return _p({}); },
        runNodesInBackground: function() {},
        stop: _void,
        onNodeState: function() { return function(){}; },
        onNodeOutput: function() { return function(){}; },
      },
      // auth module
      auth: {
        hasCredential: function() { return _p(false); },
        requestCredential: function() { return _p(null); },
        listCredentials: function() { return _p([]); },
        createCredential: _void,
      },
      // workflow module
      workflow: {
        getInfo: function() { return _p({}); },
        nodeId: '',
      },
      // resources module
      resources: {
        upload: _void, getUrl: function() { return _p(''); },
        remove: _void, list: function() { return _p([]); },
      },
      // dataset module
      dataset: {
        list: function() { return _p([]); },
        create: function() { return _p(''); },
        getRows: function() { return _p({ rows:[], total:0 }); },
        appendRows: _void, updateRow: _void, deleteRows: _void,
      },
      // inputs
      onInputsChanged: function() { return function(){}; },
      useInputs: function() { return {}; },
      // init
      init: _void,
      __esModule: true, default: null
    };
  })()
};
// require() returns the stub module or a generic proxy for unknown packages
function require(name) {
  if (_modules[name]) return _modules[name];
  return _stub();
}
// Set react's default export
_modules['react'].default = _modules['react'];
_modules['react-dom/client'].default = _modules['react-dom/client'];
_modules['react-dom'].default = _modules['react-dom'];
"""


def validate_jsx_runtime(jsx_source: str) -> Optional[str]:
    """
    Validate JSX by transpiling and executing in a stubbed browser environment.

    Catches both syntax errors (via Sucrase) and runtime errors that occur
    during module initialization and first render (e.g. calling .map() on
    a non-array, undefined variable access, etc.).

    Args:
        jsx_source: Raw JSX/TSX source code.

    Returns:
        None if the code compiles and executes without error,
        or an error message string describing the failure.
    """
    import quickjs

    start = time.perf_counter()
    try:
        ctx = quickjs.Context()
        ctx.set_memory_limit(50 * 1024 * 1024)
        ctx.set_max_stack_size(2 * 1024 * 1024)

        # Load Sucrase and transpile with import → require() conversion
        bundle = _load_sucrase_bundle()
        ctx.eval(bundle)

        # Validate the code that will actually run, including the host-mount
        # bootstrap — so a default-export-only component's render is exercised.
        jsx_source = apply_host_mount(jsx_source)
        source_json = json.dumps(jsx_source)
        result_json = ctx.eval(
            f"JSON.stringify(sucraseTransform({source_json}, {{"
            f'  transforms: ["jsx", "typescript", "imports"],'
            f'  jsxRuntime: "automatic",'
            f'  jsxImportSource: "react",'
            f"  production: true"
            f"}}))"
        )
        parsed = json.loads(result_json)
        transpiled = parsed["code"]

        # Inject browser stubs, then execute the transpiled code
        ctx.eval(_BROWSER_STUB)
        ctx.eval(transpiled)

        elapsed = (time.perf_counter() - start) * 1000
        logger.debug(f"[JSXTranspiler] Runtime validation passed in {elapsed:.1f}ms")
        return None

    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        raw = str(e)
        first_line = raw.split('\n')[0].strip()

        # Enriched errors from our state-update catch block — already descriptive
        if 'Runtime error after state update' in first_line:
            error_msg = first_line
        # Syntax errors
        elif first_line.startswith('SyntaxError:'):
            if 'unexpected token' in first_line and ('object' in first_line or 'undefined' in first_line):
                error_msg = f"JSX runtime error: {first_line}. Hint: JSON.parse() or similar was called on a non-string value (likely a Promise from state.get()). Use .then() to unwrap the value first."
            else:
                error_msg = f"JSX syntax error: {first_line}"
        # Runtime errors — add context hints
        else:
            hints = []
            if 'not a function' in first_line:
                hints.append("A value that is not a function was called as one. Check that all imported functions exist and variables are the expected type.")
            elif 'not iterable' in first_line:
                hints.append("Spread operator (...) or for-of was used on a non-iterable value. If using state.get(), remember it returns a Promise — use .then() to unwrap it first.")
            elif 'cannot read property' in first_line:
                hints.append("Accessed a property on null or undefined. Add a null check (e.g. value?.property or value && value.property).")
            elif 'cannot convert to object' in first_line:
                hints.append("Destructuring or Object method was used on null/undefined. Add a fallback (e.g. const { a } = value || {}).")
            elif 'is not defined' in first_line:
                hints.append("A variable or import is not defined. Check for typos and ensure all imports are correct.")
            hint_str = f" Hint: {hints[0]}" if hints else ""
            error_msg = f"JSX runtime error: {first_line}.{hint_str}"

        logger.info(f"[JSXTranspiler] Runtime validation failed in {elapsed:.1f}ms: {error_msg}")
        return error_msg


# --- Import extraction & map building ---

# Matches: import ... from 'pkg', import 'pkg', import('pkg')
# Ignores relative imports (starting with . or /)
_IMPORT_RE = re.compile(
    r"""(?:import\s+.*?\s+from\s+|import\s*\(?\s*)['"]([^'"./][^'"]*?)['"]""",
    re.DOTALL,
)


def extract_imports(transpiled_code: str) -> set[str]:
    """
    Extract npm package specifiers from transpiled JS code.

    Handles unscoped ('recharts') and scoped ('@mui/material') packages,
    including deep imports ('@mui/material/Button').

    Returns:
        Set of package names (e.g. {'@mui/material', 'recharts'}).
    """
    packages: set[str] = set()
    for match in _IMPORT_RE.finditer(transpiled_code):
        specifier = match.group(1)
        # Extract package name from specifier
        if specifier.startswith("@"):
            # Scoped: @scope/pkg or @scope/pkg/subpath → @scope/pkg
            parts = specifier.split("/")
            pkg_name = "/".join(parts[:2])
        else:
            # Unscoped: pkg or pkg/subpath → pkg
            pkg_name = specifier.split("/")[0]

        if pkg_name not in BUILTIN_SPECIFIERS:
            packages.add(pkg_name)
    return packages


def build_import_map(transpiled_code: str, sdk_js: Optional[str] = None) -> dict:
    """
    Build a browser import map from transpiled JS code.

    Scans code for import statements, maps each package to an esm.sh URL
    with React externalized (single React instance). Includes React/ReactDOM
    as canonical entries.

    Args:
        transpiled_code: Transpiled JS (output of transpile_jsx).
        sdk_js: Optional SDK JavaScript source. If provided, it's base64-encoded
                as a data: URI and mapped to '@noclick/sdk'.

    Returns:
        Import map dict: {"imports": {"react": "...", "pkg": "...", ...}}
    """
    imports: dict[str, str] = {
        # React singleton — always present
        "react": f"{ESM_SH}/react@{REACT_VERSION}",
        "react/": f"{ESM_SH}/react@{REACT_VERSION}/",
        "react-dom": f"{ESM_SH}/react-dom@{REACT_VERSION}?external={EXTERNAL}",
        "react-dom/": f"{ESM_SH}/react-dom@{REACT_VERSION}&external={EXTERNAL}/",
        # JSX automatic runtime (Sucrase emits 'react/jsx-runtime' imports)
        "react/jsx-runtime": f"{ESM_SH}/react@{REACT_VERSION}/jsx-runtime",
    }

    # SDK (if provided)
    if sdk_js is not None:
        import base64
        encoded = base64.b64encode(sdk_js.encode()).decode()
        imports["@noclick/sdk"] = f"data:text/javascript;base64,{encoded}"
        # SDK's WebSocket transport dynamically imports socket.io-client
        imports["socket.io-client"] = f"{ESM_SH}/socket.io-client?external={EXTERNAL}&bundle"

    # Auto-detect external packages from code.
    # Use &bundle so esm.sh bundles transitive dependencies into a single file
    # instead of emitting relative imports with version ranges (which break in import maps).
    packages = extract_imports(transpiled_code)
    # Sanitize: skip packages with characters that could break out of the JSON/HTML context
    packages = {pkg for pkg in packages if not any(c in pkg for c in '<>"')}
    for pkg in sorted(packages):
        imports[pkg] = f"{ESM_SH}/{pkg}?external={EXTERNAL}&bundle"
        # Trailing-slash entry for deep/subpath imports
        if pkg.startswith("@"):
            imports[f"{pkg}/"] = f"{ESM_SH}/{pkg}&external={EXTERNAL}&bundle/"

    return {"imports": imports}


# --- srcdoc assembly ---


def build_srcdoc(
    transpiled_code: str,
    import_map: dict,
    title: str = "NoClick Component",
) -> str:
    """
    Assemble a complete HTML document for iframe rendering.

    Includes:
    - Import map for ESM resolution (React, npm packages, SDK)
    - Tailwind CSS CDN
    - Transpiled JS as a module script
    - Root div for React mounting

    Args:
        transpiled_code: Transpiled JS code (output of transpile_jsx).
        import_map: Import map dict (output of build_import_map).
        title: HTML document title.

    Returns:
        Complete HTML string suitable for iframe srcdoc.
    """
    import_map_json = json.dumps(import_map, indent=2)

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{title}</title>
  <script type="importmap">
{import_map_json}
  </script>
  <script src="{TAILWIND_CDN}"></script>
  <style>
    body {{ margin: 0; }}
    #root {{ min-height: 100vh; }}
    .nc-error {{ color: #f87171; padding: 1rem; font-family: monospace; font-size: 13px; white-space: pre-wrap; display: none; }}
  </style>
</head>
<body>
  <div id="root"></div>
  <div id="nc-error" class="nc-error"></div>
  <script>
    window.onerror = function(msg, src, line, col, err) {{
      if (typeof msg === 'string' && msg.includes('ResizeObserver')) return true;
      var el = document.getElementById('nc-error');
      el.textContent = msg + '\\n' + (src || '') + ':' + line + ':' + col;
      el.style.display = 'block';
    }};
  </script>
  <script type="module">
{transpiled_code}
  </script>
</body>
</html>"""


# --- Full pipeline ---


def build_component(
    jsx_source: str, sdk_js: Optional[str] = None
) -> BuildResult:
    """
    Full pipeline: transpile JSX → build import map → assemble srcdoc.

    Args:
        jsx_source: JSX/TSX source code.
        sdk_js: Optional SDK JavaScript source for the @noclick/sdk import.
                If None, the built-in @noclick/sdk bundle is used automatically.

    Returns:
        BuildResult with srcdoc ready for iframe rendering, or error.
    """
    # Auto-load the SDK bundle if not explicitly provided
    if sdk_js is None:
        try:
            sdk_js = _load_sdk_bundle()
        except OSError:
            pass  # SDK not built or not accessible — components just won't have @noclick/sdk available

    total_start = time.perf_counter()

    # Step 1: Transpile
    transpile_result = transpile_jsx(jsx_source)
    if not transpile_result.success:
        return BuildResult(
            success=False,
            error=f"Transpile error: {transpile_result.error}",
            timing={"transpile_ms": transpile_result.elapsed_ms},
        )

    # Step 2: Build import map
    map_start = time.perf_counter()
    import_map = build_import_map(transpile_result.code, sdk_js)
    map_ms = (time.perf_counter() - map_start) * 1000

    # Step 3: Assemble srcdoc
    doc_start = time.perf_counter()
    srcdoc = build_srcdoc(transpile_result.code, import_map)
    doc_ms = (time.perf_counter() - doc_start) * 1000

    total_ms = (time.perf_counter() - total_start) * 1000

    return BuildResult(
        success=True,
        code=transpile_result.code,
        import_map=import_map,
        srcdoc=srcdoc,
        timing={
            "transpile_ms": round(transpile_result.elapsed_ms, 2),
            "import_map_ms": round(map_ms, 2),
            "srcdoc_ms": round(doc_ms, 2),
            "total_ms": round(total_ms, 2),
        },
    )
