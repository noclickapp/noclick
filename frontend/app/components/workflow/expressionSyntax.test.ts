// Unit tests for the shared {{ }} expression syntax helpers — the FE half of the
// classification that mirrors backend/utils/expression_evaluator.py.

import { describe, it, expect } from 'vitest';
import {
    isJsExpression,
    scanBlocks,
    getFullMatchExpression,
    pathToExpression,
    parsePureAccessor,
    normalizeAccessorRef,
    detectAccessorContext,
    blockAtCursor,
    referenceAtCursor,
} from './expressionSyntax';

describe('isJsExpression', () => {
    it('treats $-accessors as expressions', () => {
        expect(isJsExpression("$('node-1').field")).toBe(true);
        expect(isJsExpression('$vars.x * 2')).toBe(true);
        expect(isJsExpression('$json.title')).toBe(true);
        expect(isJsExpression("$ifEmpty($('n'), 'x')")).toBe(true);
    });
    it('does not treat legacy paths or literals as expressions', () => {
        expect(isJsExpression('node-1.field')).toBe(false);
        expect(isJsExpression('name')).toBe(false);
        expect(isJsExpression('price is $5')).toBe(false); // bare $5 is not an accessor
    });
});

describe('scanBlocks', () => {
    it('finds simple blocks', () => {
        const blocks = scanBlocks('a {{node.x}} b {{ $vars.y }} c');
        expect(blocks.map((b) => b.inner)).toEqual(['node.x', ' $vars.y ']);
    });
    it('tolerates inner } from object literals and strings', () => {
        const blocks = scanBlocks("{{ $('n').items.map(i => ({id: i.id})) }}");
        expect(blocks).toHaveLength(1);
        expect(blocks[0].inner).toContain('({id: i.id})');
    });
    it('does not terminate on }} inside a string literal', () => {
        const blocks = scanBlocks('{{ "}}".length }}');
        expect(blocks).toHaveLength(1);
        expect(blocks[0].inner).toBe(' "}}".length ');
    });
    it('ignores an unterminated block', () => {
        expect(scanBlocks('{{ unterminated')).toHaveLength(0);
    });
});

describe('getFullMatchExpression', () => {
    it('returns the inner for a whole-field expression', () => {
        expect(getFullMatchExpression("{{ $('n').x.split(',') }}")).toBe("$('n').x.split(',')");
        expect(getFullMatchExpression("  {{ $vars.a }}  ")).toBe('$vars.a');
    });
    it('returns null for legacy refs, literals, mixed, or multiple', () => {
        expect(getFullMatchExpression('{{node-1.field}}')).toBeNull(); // legacy ref
        expect(getFullMatchExpression('{{name}}')).toBeNull(); // literal
        expect(getFullMatchExpression("pre {{ $vars.a }}")).toBeNull(); // mixed
        expect(getFullMatchExpression("{{ $vars.a }}{{ $vars.b }}")).toBeNull(); // multiple
    });
});

describe('parsePureAccessor', () => {
    it('parses transform-free accessors into nodeId + path', () => {
        expect(parsePureAccessor("$('node-1').message")).toEqual({ nodeId: 'node-1', path: 'message' });
        expect(parsePureAccessor("$('n').items[0].title")).toEqual({ nodeId: 'n', path: 'items[0].title' });
        expect(parsePureAccessor("$('n')")).toEqual({ nodeId: 'n', path: '' });
        expect(parsePureAccessor('$vars.api_base')).toEqual({ nodeId: 'vars', path: 'api_base' });
    });
    it('returns null for transforms and $json', () => {
        expect(parsePureAccessor("$('n').csv.split(',')")).toBeNull(); // has a call
        expect(parsePureAccessor('$vars.x * 2')).toBeNull(); // has an operator
        expect(parsePureAccessor('$json.title')).toBeNull(); // $json has no node to validate
    });
});

describe('normalizeAccessorRef', () => {
    it('converts pure accessors to the legacy nodeId.path form', () => {
        expect(normalizeAccessorRef("$('node-1').message")).toBe('node-1.message');
        expect(normalizeAccessorRef('$vars.x')).toBe('vars.x');
        expect(normalizeAccessorRef("$('n')")).toBe('n');
    });
    it('passes legacy refs through unchanged', () => {
        expect(normalizeAccessorRef('node-1.message')).toBe('node-1.message');
    });
});

describe('detectAccessorContext', () => {
    const at = (s: string) => detectAccessorContext(s, s.length); // cursor at end

    it('detects the node picker inside $(\'<partial>', () => {
        const ctx = at("{{ $('");
        expect(ctx).toMatchObject({ kind: 'node', partial: '' });
        const ctx2 = at("{{ $('what");
        expect(ctx2).toMatchObject({ kind: 'node', partial: 'what' });
        // quoteStart points at the char right after the opening quote
        expect("{{ $('what".slice((ctx2 as { quoteStart: number }).quoteStart)).toBe('what');
    });

    it('detects the field picker after $(\'nodeId\').', () => {
        const ctx = at("{{ $('node-1').");
        expect(ctx).toMatchObject({ kind: 'field', nodeId: 'node-1', partial: '' });
        const ctx2 = at("{{ $('node-1').mes");
        expect(ctx2).toMatchObject({ kind: 'field', nodeId: 'node-1', partial: 'mes' });
    });

    it('returns null for legacy {{node.field}} (old reference autocomplete deprecated)', () => {
        expect(at('{{ node-1.mes')).toBeNull();
        expect(at('{{node-1')).toBeNull();
    });

    it('returns null when closed or inside a richer expression', () => {
        expect(at('{{ $vars.x }} done')).toBeNull(); // closed before cursor
        expect(at("{{ $('n').x.split(',')")).toBeNull(); // past a transform, no clean context
        expect(at('plain text')).toBeNull();
    });
});

describe('blockAtCursor', () => {
    const v = "You are {{ $('x').role }} today";
    const start = v.indexOf('{{');
    const end = v.indexOf('}}') + 2;

    it('finds the $() block the cursor sits inside (embedded in text)', () => {
        const b = blockAtCursor(v, start + 5); // inside the block
        expect(b).not.toBeNull();
        expect(b!.inner.trim()).toBe("$('x').role");
        expect(b!.start).toBe(start);
        expect(b!.end).toBe(end);
    });
    it('returns null when the cursor is in plain text', () => {
        expect(blockAtCursor(v, 2)).toBeNull(); // in "You are"
        expect(blockAtCursor(v, v.length - 2)).toBeNull(); // in "today"
    });
    it('ignores legacy {{node.field}} and literal blocks', () => {
        expect(blockAtCursor('hi {{node-1.name}}!', 8)).toBeNull();
        expect(blockAtCursor('hi {{name}}!', 8)).toBeNull();
    });
    it('opens for an empty {{ }} block the user just started', () => {
        expect(blockAtCursor('{{  }}', 3)).not.toBeNull(); // whitespace inner
        expect(blockAtCursor('{{}}', 2)).not.toBeNull(); // no inner
        const b = blockAtCursor('greeting {{ }} here', 12);
        expect(b).not.toBeNull();
        expect(b!.inner.trim()).toBe('');
    });
});

describe('referenceAtCursor', () => {
    it('resolves a pure $() accessor to nodeId + path', () => {
        const v = "Hi {{ $('gmail_vfgs').type }} there";
        expect(referenceAtCursor(v, v.indexOf('type'))).toEqual({ nodeId: 'gmail_vfgs', path: 'type' });
    });
    it('resolves a nested/indexed accessor path', () => {
        const v = "{{ $('sheets').headers[8].name }}";
        expect(referenceAtCursor(v, 10)).toEqual({ nodeId: 'sheets', path: 'headers[8].name' });
    });
    it('resolves a legacy {{node.field}} reference', () => {
        const v = 'x {{node-1.message.text}} y';
        expect(referenceAtCursor(v, v.indexOf('message'))).toEqual({ nodeId: 'node-1', path: 'message.text' });
    });
    it('points a transform expression at the first node it reads (no path)', () => {
        const v = "{{ $('node-1').csv.split(',')[0] }}";
        expect(referenceAtCursor(v, 12)).toEqual({ nodeId: 'node-1', path: '' });
    });
    it('resolves $vars accessors', () => {
        const v = '{{ $vars.threshold }}';
        expect(referenceAtCursor(v, 10)).toEqual({ nodeId: 'vars', path: 'threshold' });
    });
    it('returns null when the cursor is outside any reference', () => {
        expect(referenceAtCursor("plain {{ $('n').f }} text", 2)).toBeNull();
        expect(referenceAtCursor('no refs at all', 5)).toBeNull();
    });
});

describe('pathToExpression', () => {
    it('builds a $() accessor with a dotted path', () => {
        expect(pathToExpression('node-1', 'message')).toBe("$('node-1').message");
        expect(pathToExpression('node-1', 'items[0].title')).toBe("$('node-1').items[0].title");
    });
    it('returns just the node accessor for an empty path', () => {
        expect(pathToExpression('node-1', '')).toBe("$('node-1')");
    });
    it('brackets non-identifier keys', () => {
        expect(pathToExpression('node-1', 'First Name')).toBe("$('node-1')['First Name']");
    });
    it('escapes node IDs and keys as complete single-quoted JavaScript strings', () => {
        expect(pathToExpression("node\\'one", "line\nbreak\\path'key")).toBe(
            "$('node\\\\\\'one')['line\\nbreak\\\\path\\'key']",
        );
    });
});
