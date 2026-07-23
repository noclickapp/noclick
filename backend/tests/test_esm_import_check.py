"""
Tests for the static esm.sh import/export checker (utils/esm_import_check).

Network is stubbed with realistic esm.sh-shaped module text (a re-export wrapper
pointing at a versioned terminal module) so the tests exercise the real parsing,
`export *` following, diffing, and fail-open behavior — not mock behavior.
"""

import pytest

from utils.esm_import_check import (
    check_jsx_imports,
    parse_imports,
    parse_exports,
)

# esm.sh serves a thin re-export wrapper that points at a versioned terminal module.
LUCIDE_WRAPPER_URL = "https://esm.sh/lucide-react?external=react,react-dom&bundle"
LUCIDE_TERMINAL_URL = "https://esm.sh/lucide-react@1.26.0/es2022/lucide-react.mjs"
LUCIDE_WRAPPER = (
    'export * from "/lucide-react@1.26.0/es2022/lucide-react.mjs";\n'
    'export { default } from "/lucide-react@1.26.0/es2022/lucide-react.mjs";\n'
)
# Terminal export list — the generic icons the runtime still provides. Brand icons
# (Github, Linkedin, Twitter) are intentionally absent, mirroring lucide 1.x.
LUCIDE_TERMINAL = (
    "export{Mail as Mail,Send as Send,User as User,ArrowUpRight as ArrowUpRight,"
    "ExternalLink as ExternalLink,MessageSquare as MessageSquare,Menu as Menu};"
)

FRAMER_URL = "https://esm.sh/framer-motion?external=react,react-dom&bundle"
FRAMER_MODULE = "export{motion as motion,AnimatePresence as AnimatePresence};\nexport const useScroll=()=>{};\nexport function useTransform(){}"


def fake_fetch_factory(table, *, record=None):
    async def _fetch(url):
        if record is not None:
            record.append(url)
        return table.get(url)
    return _fetch


LUCIDE_TABLE = {LUCIDE_WRAPPER_URL: LUCIDE_WRAPPER, LUCIDE_TERMINAL_URL: LUCIDE_TERMINAL}


@pytest.mark.asyncio
async def test_detects_removed_lucide_brand_icons():
    # The exact reported failure: the model imported lucide brand icons that 1.x removed.
    jsx = (
        "import React from 'react';\n"
        "import { Github, Linkedin, Twitter, Mail, Send, User } from 'lucide-react';\n"
        "function App(){ return null }\n"
    )
    err = await check_jsx_imports(jsx, fetch=fake_fetch_factory(LUCIDE_TABLE), cache={})
    assert err is not None
    # Flags the removed ones...
    assert "no export named 'Github'" in err
    assert "no export named 'Linkedin'" in err
    assert "no export named 'Twitter'" in err
    # ...but NOT the ones that still exist.
    assert "'Mail'" not in err and "'Send'" not in err and "'User'" not in err
    # Actionable guidance for the model.
    assert "lucide-react removed brand/logo icons" in err
    assert "Mail" in err  # available-exports sample


@pytest.mark.asyncio
async def test_all_valid_imports_return_none():
    jsx = (
        "import { Mail, Send, Menu } from 'lucide-react';\n"
        "import { motion, useScroll, useTransform } from 'framer-motion';\n"
    )
    table = {**LUCIDE_TABLE, FRAMER_URL: FRAMER_MODULE}
    assert await check_jsx_imports(jsx, fetch=fake_fetch_factory(table), cache={}) is None


@pytest.mark.asyncio
async def test_fail_open_when_package_unfetchable():
    # Fetch returns None (404/timeout/etc.) → export set unknown → never flag.
    jsx = "import { DefinitelyNotReal } from 'lucide-react';\n"
    err = await check_jsx_imports(jsx, fetch=fake_fetch_factory({}), cache={})
    assert err is None


@pytest.mark.asyncio
async def test_fail_open_when_star_reexport_unresolved():
    # Wrapper points at a terminal we can't fetch → partial set → must not flag.
    jsx = "import { Github } from 'lucide-react';\n"
    table = {LUCIDE_WRAPPER_URL: LUCIDE_WRAPPER}  # terminal missing
    assert await check_jsx_imports(jsx, fetch=fake_fetch_factory(table), cache={}) is None


@pytest.mark.asyncio
async def test_default_and_namespace_imports_not_checked():
    # Default + namespace bindings are never checked (esm.sh synthesizes defaults;
    # a namespace binds whatever exists). Only named imports are verified.
    jsx = (
        "import Lucide from 'lucide-react';\n"
        "import * as Icons from 'lucide-react';\n"
    )
    assert await check_jsx_imports(jsx, fetch=fake_fetch_factory(LUCIDE_TABLE), cache={}) is None


@pytest.mark.asyncio
async def test_offhost_star_reexport_is_not_fetched_and_fails_open():
    # A re-export pointing off esm.sh must never be fetched, and (being unresolved)
    # makes the whole package fail-open rather than false-flagging.
    record = []
    wrapper = 'export * from "https://evil.example/x.mjs";\n'
    table = {LUCIDE_WRAPPER_URL: wrapper}
    err = await check_jsx_imports(
        "import { Github } from 'lucide-react';\n",
        fetch=fake_fetch_factory(table, record=record), cache={},
    )
    assert err is None
    assert not any("evil.example" in u for u in record)


@pytest.mark.asyncio
async def test_named_reexport_counts_as_export():
    # `export { X } from './chunk'` names X as an export of this module — no need to
    # follow the chunk for the name.
    jsx = "import { Foo } from 'somepkg';\n"
    table = {"https://esm.sh/somepkg?external=react,react-dom&bundle": 'export { Foo, Bar } from "./chunk.mjs";'}
    assert await check_jsx_imports(jsx, fetch=fake_fetch_factory(table), cache={}) is None


# ── Pure parser unit tests ───────────────────────────────────────────────────

def test_parse_imports_forms():
    src = (
        "import React from 'react';\n"
        "import { a, b as c,\n  d } from 'pkg1';\n"
        "import Default, { e } from 'pkg2';\n"
        "import * as NS from 'pkg3';\n"
        "import 'side-effect';\n"
        "// import { fake } from 'commented';\n"
    )
    imports = parse_imports(src)
    assert imports['pkg1'].named == {'a', 'b', 'd'}  # source side of `as`
    assert imports['pkg2'].named == {'e'} and imports['pkg2'].default is True
    assert imports['pkg3'].namespace is True and not imports['pkg3'].named
    assert 'commented' not in imports  # line-anchored: `//` comment not matched
    assert 'side-effect' not in imports  # no named bindings → not a target


def test_parse_exports_forms():
    text = (
        "export { A as A, B, C as default } from './x';\n"
        "export const D = 1;\n"
        "export function E(){}\n"
        "export * from './y';\n"
        "export default function(){}\n"
    )
    names, has_default, stars = parse_exports(text)
    assert {'A', 'B', 'D', 'E'} <= names
    assert 'C' not in names  # C was re-exported AS default
    assert has_default is True
    assert stars == ['./y']
