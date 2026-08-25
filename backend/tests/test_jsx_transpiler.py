"""Tests for the JSX transpiler module."""

import pytest

from utils.jsx_transpiler import (
    TranspileResult,
    BuildResult,
    apply_patch,
    apply_host_mount,
    transpile_jsx,
    validate_jsx_runtime,
    extract_imports,
    build_import_map,
    build_srcdoc,
    build_component,
)


# --- Transpilation tests ---


class TestTranspileJsx:
    def test_basic_jsx(self):
        result = transpile_jsx("<div>hello</div>")
        assert result.success
        assert "jsx" in result.code
        assert "div" in result.code
        assert result.elapsed_ms > 0

    def test_full_component(self):
        source = """
import React, { useState } from 'react';
import ReactDOM from 'react-dom/client';

function App() {
  const [count, setCount] = useState(0);
  return (
    <div>
      <h1>Counter</h1>
      <p>Count: {count}</p>
      <button onClick={() => setCount(c => c + 1)}>+</button>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
"""
        result = transpile_jsx(source)
        assert result.success
        # JSX should be converted to jsx/jsxs calls
        assert "jsx" in result.code
        # Imports preserved
        assert "useState" in result.code
        assert "react-dom/client" in result.code

    def test_typescript_stripped(self):
        source = """
interface Props { title: string; count: number }
const App = ({ title, count }: Props) => <div>{title}: {count}</div>;
"""
        result = transpile_jsx(source)
        assert result.success
        # TypeScript annotations should be gone
        assert "interface" not in result.code
        assert ": Props" not in result.code
        assert ": string" not in result.code
        # Functional code preserved
        assert "title" in result.code
        assert "count" in result.code

    def test_external_package_import(self):
        source = """
import { Button } from '@mui/material';
const App = () => <Button variant="contained">Click</Button>;
"""
        result = transpile_jsx(source)
        assert result.success
        assert "@mui/material" in result.code
        assert "Button" in result.code

    def test_syntax_error(self):
        result = transpile_jsx("<div>unclosed")
        assert not result.success
        assert result.error

    def test_automatic_jsx_runtime(self):
        """Verify Sucrase uses automatic JSX runtime (react/jsx-runtime imports)."""
        result = transpile_jsx("<div>test</div>")
        assert result.success
        assert "react/jsx-runtime" in result.code


# --- Import extraction tests ---


class TestExtractImports:
    def test_basic_imports(self):
        code = """
import { useState } from 'react';
import { Button } from '@mui/material';
import Chart from 'recharts';
"""
        pkgs = extract_imports(code)
        # react is a builtin, should be excluded
        assert "react" not in pkgs
        assert "@mui/material" in pkgs
        assert "recharts" in pkgs

    def test_deep_imports(self):
        code = "import Button from '@mui/material/Button';"
        pkgs = extract_imports(code)
        assert "@mui/material" in pkgs

    def test_relative_imports_ignored(self):
        code = """
import { foo } from './utils';
import { bar } from '../lib';
import { baz } from '/absolute';
"""
        pkgs = extract_imports(code)
        assert len(pkgs) == 0

    def test_multiple_packages(self):
        code = """
import { LineChart } from 'recharts';
import { format } from 'date-fns';
import { motion } from 'framer-motion';
"""
        pkgs = extract_imports(code)
        assert pkgs == {"recharts", "date-fns", "framer-motion"}

    def test_dynamic_import(self):
        code = "const mod = import('lodash');"
        pkgs = extract_imports(code)
        assert "lodash" in pkgs


# --- Import map tests ---


class TestBuildImportMap:
    def test_has_react_entries(self):
        im = build_import_map("")
        imports = im["imports"]
        assert "react" in imports
        assert "react-dom" in imports
        assert "react/jsx-runtime" in imports

    def test_detected_packages(self):
        code = "import { Button } from '@mui/material';\nimport Chart from 'recharts';"
        im = build_import_map(code)
        imports = im["imports"]
        assert "@mui/material" in imports
        assert "esm.sh" in imports["@mui/material"]
        assert "recharts" in imports
        # Scoped package gets trailing-slash entry
        assert "@mui/material/" in imports

    def test_external_react(self):
        """All package URLs should externalize react and bundle deps."""
        code = "import X from 'some-pkg';"
        im = build_import_map(code)
        assert "external=react,react-dom" in im["imports"]["some-pkg"]
        assert "&bundle" in im["imports"]["some-pkg"]


# --- Patch application tests (re-exported from patch_utils) ---


class TestApplyPatch:
    """Verify apply_patch (from patch_utils) works for JSX source editing."""

    def test_simple_replace(self):
        source = "const title = 'Hello';\nconst count = 0;"
        patch = """*** Begin Patch
@@ const title = 'Hello';
-const title = 'Hello';
+const title = 'World';
*** End Patch"""
        result = apply_patch(source, patch)
        assert "World" in result
        assert "Hello" not in result

    def test_insert_line(self):
        source = "import React from 'react';\n\nfunction App() {"
        patch = """*** Begin Patch
@@ import React from 'react';
+import { useState } from 'react';
*** End Patch"""
        result = apply_patch(source, patch)
        assert "useState" in result
        assert "import React" in result

    def test_multi_chunk_jsx_edit(self):
        source = "function App() {\n  return <div>Old</div>;\n}\n"
        patch = """*** Begin Patch
@@ function App() {
-  return <div>Old</div>;
+  return <div>New</div>;
*** End Patch"""
        result = apply_patch(source, patch)
        assert "<div>New</div>" in result
        assert "<div>Old</div>" not in result

    def test_re_exported_from_jsx_transpiler(self):
        """Verify apply_patch is importable from jsx_transpiler."""
        from coder.workflow.patch_utils import apply_patch as original
        assert apply_patch is original


# --- srcdoc assembly tests ---


class TestBuildSrcdoc:
    def test_contains_essentials(self):
        code = "console.log('hello');"
        im = {"imports": {"react": "https://esm.sh/react"}}
        html = build_srcdoc(code, im)

        assert "<!DOCTYPE html>" in html
        assert '<div id="root">' in html
        assert '<script type="importmap">' in html
        assert '<script type="module">' in html
        assert "console.log('hello');" in html
        assert "tailwindcss" in html

    def test_import_map_embedded(self):
        im = {"imports": {"react": "https://esm.sh/react@19", "foo": "https://esm.sh/foo"}}
        html = build_srcdoc("", im)
        assert "esm.sh/react@19" in html
        assert "esm.sh/foo" in html


# --- Full pipeline tests ---


class TestBuildComponent:
    def test_full_pipeline(self):
        source = """
import React, { useState } from 'react';
import ReactDOM from 'react-dom/client';

function App() {
  return <div className="p-4"><h1>Hello</h1></div>;
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
"""
        result = build_component(source)
        assert result.success
        assert result.code  # Transpiled JS
        assert result.import_map  # Import map dict
        assert result.srcdoc  # Full HTML
        assert "<!DOCTYPE html>" in result.srcdoc
        assert result.timing["transpile_ms"] > 0
        assert result.timing["total_ms"] > 0

    def test_with_external_packages(self):
        source = """
import React from 'react';
import ReactDOM from 'react-dom/client';
import { Button } from '@mui/material';
import { LineChart } from 'recharts';

const App = () => <div><Button>Click</Button><LineChart /></div>;
ReactDOM.createRoot(document.getElementById('root')).render(<App />);
"""
        result = build_component(source)
        assert result.success
        imports = result.import_map["imports"]
        assert "@mui/material" in imports
        assert "recharts" in imports

    def test_transpile_error_propagates(self):
        result = build_component("<div>unclosed")
        assert not result.success
        assert "error" in result.error.lower() or "Transpile" in result.error


# --- Host-mount transform tests ---


SELF_MOUNT = """import React from 'react';
import ReactDOM from 'react-dom/client';
function App(){ return <div>hi</div>; }
ReactDOM.createRoot(document.getElementById('root')).render(<App/>);
"""

ARTIFACTS_NAMED = """import React, { useState } from 'react';
export default function App(){ const [n,setN]=useState(0); return <button onClick={()=>setN(n+1)}>{n}</button>; }
"""


class TestHostMount:
    """apply_host_mount: accept Artifacts-style export-default code while leaving
    self-mounting (existing/published/builder) code byte-identical."""

    def test_self_mount_unchanged(self):
        # Existing/published code already calls createRoot -> never rewritten.
        assert apply_host_mount(SELF_MOUNT) == SELF_MOUNT

    def test_react_dom_client_import_treated_as_self_mount(self):
        # Even with createRoot aliased, the react-dom/client import is the tell.
        src = ("import { createRoot as mount } from 'react-dom/client';\n"
               "export default function App(){ return <div>x</div>; }\n"
               "mount(document.getElementById('root')).render(<App/>);")
        assert apply_host_mount(src) == src

    def test_method_named_createRoot_is_not_a_self_mount(self):
        # A non-React `obj.createRoot(...)` must NOT suppress host-mount.
        src = ("import React from 'react';\n"
               "const pool = { createRoot(){ return 1; } };\n"
               "export default function App(){ pool.createRoot(); return <div/>; }\n")
        out = apply_host_mount(src)
        assert "const __ncDefault = App;" in out
        assert "__ncCreateRoot" in out  # host-mount bootstrap WAS appended

    def test_named_default_captured(self):
        out = apply_host_mount(ARTIFACTS_NAMED)
        assert "export default function" not in out
        assert "const __ncDefault = App;" in out
        assert "__ncCreateRoot" in out

    def test_arrow_default_captured(self):
        out = apply_host_mount(
            "import React from 'react';\nconst App = () => <div/>;\nexport default App;\n"
        )
        assert "const __ncDefault = App;" in out

    def test_brace_default_captured(self):
        out = apply_host_mount(
            "import React from 'react';\nfunction App(){ return <div/>; }\nexport { App as default };\n"
        )
        assert "as default" not in out
        assert "const __ncDefault = App;" in out

    def test_no_default_appends_hint_bootstrap(self):
        out = apply_host_mount(
            "import React from 'react';\nfunction A(){ return <div/>; }\nfunction B(){ return <div/>; }\n"
        )
        assert "__ncCreateRoot" in out          # bootstrap appended
        assert "const __ncDefault =" not in out  # nothing captured -> hint path

    def test_idempotent(self):
        once = apply_host_mount(ARTIFACTS_NAMED)
        assert apply_host_mount(once) == once

    def test_empty_unchanged(self):
        assert apply_host_mount("") == ""
        assert apply_host_mount("   \n  ") == "   \n  "

    def test_transpile_self_mount_not_doubled(self):
        result = transpile_jsx(SELF_MOUNT)
        assert result.success
        assert result.code.count("createRoot") == 1

    def test_transpile_artifacts_gets_mount(self):
        result = transpile_jsx(ARTIFACTS_NAMED)
        assert result.success
        assert "createRoot" in result.code  # host-mounted

    def test_build_component_renders_artifacts(self):
        result = build_component(ARTIFACTS_NAMED)
        assert result.success
        assert 'id="root"' in result.srcdoc
        assert "createRoot" in result.code

    def test_validator_exercises_host_mounted_component(self):
        # Valid default-export component passes (and IS rendered, not skipped).
        assert validate_jsx_runtime(ARTIFACTS_NAMED) is None
        # A default-export component with a render-time bug is still caught.
        broken = ("import React from 'react';\n"
                  "export default function App(){ return <div>{missingVar.map(x=>x)}</div>; }\n")
        err = validate_jsx_runtime(broken)
        assert err is not None
        assert "missingVar" in err


# Regression (2026-07-30): a boolean loading state flipped by an effect makes
# a later validation render can execute a DIFFERENT conditional branch whose components call more
# useState hooks than the initial render allocated. The global slot array indexed past its
# end and crashed with "cannot read property 'updated' of undefined" — blamed
# on the user's (legal) React code, sending the builder into patch loops.
BOOLEAN_LOADER_BRANCH_SWITCH = """
import React, { useState, useEffect } from 'react';
import ReactDOM from 'react-dom/client';

function PageLoader({ onComplete }) {
  useEffect(() => {
    const t = setTimeout(() => onComplete(), 2500);
    return () => clearTimeout(t);
  }, []);
  return <div>Loading…</div>;
}

function Content() {
  const [tab, setTab] = useState('home');
  const [open, setOpen] = useState(false);
  return <div onClick={() => setOpen(!open)}>{tab}</div>;
}

function App() {
  const [loading, setLoading] = useState(true);
  return loading ? <PageLoader onComplete={() => setLoading(false)} /> : <Content />;
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
"""


class TestSecondRenderBranchSwitch:
    def test_boolean_loader_branch_switch_validates(self):
        assert validate_jsx_runtime(BOOLEAN_LOADER_BRANCH_SWITCH) is None

    def test_second_render_still_catches_real_bugs_in_new_branch(self):
        # The freshly-mounted branch is EXECUTED in the later validation render, so a genuine
        # render-time bug there must still fail validation.
        broken = BOOLEAN_LOADER_BRANCH_SWITCH.replace(
            "<div onClick={() => setOpen(!open)}>{tab}</div>",
            "<div>{missingContentVar.map(x => x)}</div>",
        )
        err = validate_jsx_runtime(broken)
        assert err is not None
        assert "missingContentVar" in err
