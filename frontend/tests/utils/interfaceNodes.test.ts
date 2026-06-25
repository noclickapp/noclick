// Unit coverage for the interface-node predicates in app/utils/interfaceNodes.ts.
// Focus is interfaceNodeHasContent, which gates the quick-publish banner: it must read
// "has renderable source" correctly across JSX mode, HTML mode edited in-session
// (data.config.content), and HTML mode loaded from the backend (data.content top-level —
// `content` is a shared-slot field, see TOP_LEVEL_FIELDS in applyNodeUpdate.ts). Added
// because the slot collision is easy to get wrong and isn't covered by the browser tests.

import { describe, it, expect } from 'vitest';
import {
    interfaceNodeHasContent,
    isFullscreenInterfaceNode,
    isFullscreenValue,
} from '~/utils/interfaceNodes';

describe('interfaceNodeHasContent', () => {
    it('is false for a freshly dropped node (empty config)', () => {
        expect(interfaceNodeHasContent({ config: {} })).toBe(false);
        expect(interfaceNodeHasContent({})).toBe(false);
        expect(interfaceNodeHasContent(null)).toBe(false);
        expect(interfaceNodeHasContent(undefined)).toBe(false);
    });

    it('is false when the source field is present but blank/whitespace', () => {
        expect(interfaceNodeHasContent({ config: { jsx_source: '' } })).toBe(false);
        expect(interfaceNodeHasContent({ config: { jsx_source: '   \n\t ' } })).toBe(false);
        expect(interfaceNodeHasContent({ config: { content: '   ' } })).toBe(false);
        expect(interfaceNodeHasContent({ content: '  ' })).toBe(false);
    });

    it('is true for a filled JSX node (config.jsx_source)', () => {
        expect(
            interfaceNodeHasContent({ config: { operation: 'render_jsx_react_interface', jsx_source: 'export default () => null;' } }),
        ).toBe(true);
    });

    it('is true for an HTML node edited in-session (config.content)', () => {
        expect(
            interfaceNodeHasContent({ config: { operation: 'render_html_interface', content: '<h1>hi</h1>' } }),
        ).toBe(true);
    });

    it('is true for an HTML node loaded from the backend (top-level data.content)', () => {
        // After a save/reload round-trip `content` is routed to the top-level slot, NOT config —
        // the regression the helper signature change guards against.
        expect(interfaceNodeHasContent({ content: '<h1>hi</h1>', config: { operation: 'render_html_interface' } })).toBe(true);
    });

    it('ignores non-string source values', () => {
        expect(interfaceNodeHasContent({ config: { jsx_source: 123 as unknown as string } })).toBe(false);
        expect(interfaceNodeHasContent({ content: { nested: true } as unknown as string })).toBe(false);
    });
});

describe('isFullscreenValue / isFullscreenInterfaceNode', () => {
    it('treats absent/true as fullscreen, explicit false as not', () => {
        expect(isFullscreenValue(undefined)).toBe(true);
        expect(isFullscreenValue('true')).toBe(true);
        expect(isFullscreenValue('false')).toBe(false);
        expect(isFullscreenValue(false)).toBe(false);
    });

    it('only matches interface-html-react nodes that are fullscreen', () => {
        expect(isFullscreenInterfaceNode('interface-html-react', {})).toBe(true);
        expect(isFullscreenInterfaceNode('interface-html-react', { fullscreen: 'false' })).toBe(false);
        expect(isFullscreenInterfaceNode('slack', {})).toBe(false);
    });
});
