// Verifies the inline-expression classification end-to-end against the
// REAL bundled modules: a `{{ }}` block using a `$`-accessor renders as a ƒ expression
// segment (never validated as a reference), a legacy dotted path stays a reference
// segment, and a no-dot literal stays text. Also pins drag-drop's `$()` emission.
//
// Run: mcp__nc__nc_run_test({ file: "tests/nc/inline-expressions.test.ts" })

import { nc } from '~/lib/nc';
import { parseValueIntoSegments } from '~/components/workflow/ReferenceHighlight';
import { createReferenceString } from '~/components/workflow/DroppableTextField';
import { isJsExpression, getFullMatchExpression } from '~/components/workflow/expressionSyntax';

export default async function () {
    // A $-accessor WITH a transform is an expression segment (violet, never red-flagged).
    const exprSegs = parseValueIntoSegments("{{ $('node-1').csv.split(',')[0] }}");
    nc.assert.equal(exprSegs.length, 1, 'one segment');
    nc.assert.equal(exprSegs[0].type, 'expression', 'expression segment for a $-transform');

    // A transform-free $() accessor is a reference segment (renders like a reference).
    const pureSegs = parseValueIntoSegments("{{ $('node-1').message }}");
    nc.assert.equal(pureSegs[0].type, 'reference', 'reference segment for a pure $() accessor');

    // A legacy dotted path stays a reference segment (today's behaviour, unchanged).
    const refSegs = parseValueIntoSegments('{{node-1.message}}');
    nc.assert.equal(refSegs[0].type, 'reference', 'reference segment for legacy path');

    // A no-dot literal stays text (downstream-templating passthrough).
    const litSegs = parseValueIntoSegments('Hello {{name}}!');
    nc.assert.truthy(
        litSegs.every((s) => s.type === 'text'),
        'literal {{name}} stays text',
    );

    // Mixed text + expression: text spans verbatim, the $-transform block is an expression.
    const mixed = parseValueIntoSegments("Hi {{ $('n').name.toUpperCase() }}!");
    nc.assert.includes(mixed.map((s) => s.type), 'expression', 'mixed string has an expression segment');

    // Drag-drop emits the $() accessor form, immediately transform-ready.
    nc.assert.equal(
        createReferenceString('node-1', 'message'),
        "{{ $('node-1').message }}",
        'drag-drop emits $() form',
    );

    // Helper sanity.
    nc.assert.truthy(isJsExpression("$('n').x"), 'isJsExpression true for $-accessor');
    nc.assert.equal(getFullMatchExpression("{{ $vars.a }}"), '$vars.a', 'full-match inner extracted');

    return { ok: true, expr: exprSegs[0].type, ref: refSegs[0].type };
}
