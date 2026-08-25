// Unit tests for resolveInterfaceBlockLabel — the single rule that names an
// interface node everywhere it's shown: its canvas header (InterfaceNode) AND
// its Interface sub-tab / grid-card (WorkflowInterface). Regression guard for the
// bug where sub-tabs ignored the node's own name and always read "HTML / React":
// the node's metadata label (data.label) must win over the generic block-type
// label, so two same-type interface nodes render as distinct, named tabs.

import { describe, it, expect } from 'vitest';
import { resolveInterfaceBlockLabel } from '~/utils/interfaceNodes';

describe('resolveInterfaceBlockLabel', () => {
    it('prefers the node metadata label (what canvas rename / the AI builder set)', () => {
        expect(
            resolveInterfaceBlockLabel(
                'Dashboard',
                'nested',
                'HTML / React',
                'interface-html-react'
            )
        ).toBe('Dashboard');
    });

    it('falls back to the legacy nested config.label when no metadata label', () => {
        expect(
            resolveInterfaceBlockLabel(
                undefined,
                'My Report',
                'HTML / React',
                'interface-html-react'
            )
        ).toBe('My Report');
    });

    it('falls back to the block-type label only when the node is unnamed', () => {
        expect(
            resolveInterfaceBlockLabel(
                undefined,
                undefined,
                'HTML / React',
                'interface-html-react'
            )
        ).toBe('HTML / React');
    });

    it('falls back to the raw type when even the block-type label is missing', () => {
        expect(
            resolveInterfaceBlockLabel(
                undefined,
                undefined,
                undefined,
                'interface-html-react'
            )
        ).toBe('interface-html-react');
    });

    it('two same-type nodes with distinct metadata labels resolve to distinct names', () => {
        const a = resolveInterfaceBlockLabel(
            'Dashboard',
            undefined,
            'HTML / React',
            'interface-html-react'
        );
        const b = resolveInterfaceBlockLabel(
            'Settings',
            undefined,
            'HTML / React',
            'interface-html-react'
        );
        expect(a).toBe('Dashboard');
        expect(b).toBe('Settings');
        expect(a).not.toBe(b);
        expect(a).not.toBe('HTML / React');
    });
});
