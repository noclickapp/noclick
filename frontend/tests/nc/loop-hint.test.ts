// Verifies the "Loop over each item" affordance helpers: plain-ref detection
// (the gap the tester hit — {{split-out.items}} with no []), the unified rewrite
// that converts both [] and plain array refs to per-item form, and the array-
// output detection behind the under-field "Loop over each item" button.
// Run: nc_run_test({ file: "tests/nc/loop-hint.test.ts" })
import { nc } from '~/lib/nc';
import {
  parseWholeReference,
  parseListReference,
  splitAtFirstIndex,
  rewriteListRefsForIteration,
} from '~/lib/listReferences';
import { getNodeArrayOutputPath } from '~/lib/arrayOutput';

export default async function () {
  // --- plain {{node.path}} detection (the non-[] case) ---
  nc.assert.deepEqual(
    parseWholeReference('{{split-out_1.items}}'),
    { nodeId: 'split-out_1', arrayPath: 'items' },
    'plain array ref parses',
  );
  nc.assert.deepEqual(
    parseWholeReference('  {{ src.data.records }}  '),
    { nodeId: 'src', arrayPath: 'data.records' },
    'whitespace + nested path',
  );
  nc.assert.equal(parseWholeReference('{{src.items[].x}}'), null, '[] map ref routes to the list-ref path, not "whole"');
  nc.assert.equal(parseWholeReference('url: {{src.items}}/x'), null, 'embedded ref is not "whole"');
  // Numeric indices are part of the path ({{x.values[5]}} = row 5, itself an array).
  nc.assert.deepEqual(
    parseWholeReference('{{sheets.values[5]}}'),
    { nodeId: 'sheets', arrayPath: 'values[5]' },
    'indexed ref parses',
  );
  nc.assert.deepEqual(
    parseWholeReference('{{sheets.values[5][1]}}'),
    { nodeId: 'sheets', arrayPath: 'values[5][1]' },
    'doubly-indexed ref parses',
  );

  // --- splitAtFirstIndex: loop the OUTERMOST array (prefix before first [n]) ---
  nc.assert.deepEqual(splitAtFirstIndex('values'), { prefix: 'values', hasIndex: false }, 'no index -> whole path');
  nc.assert.deepEqual(splitAtFirstIndex('values[8][1]'), { prefix: 'values', hasIndex: true }, 'loop the outer array');
  nc.assert.deepEqual(splitAtFirstIndex('data.rows[3].name'), { prefix: 'data.rows', hasIndex: true }, 'nested prefix');

  // --- the [] path still works (no regression) ---
  nc.assert.equal(parseListReference('{{s.items[].url}}')?.remainder, 'url', '[] ref still parses');

  // --- unified rewrite: BOTH plain and [] -> per-item form ---
  nc.assert.equal(
    rewriteListRefsForIteration('{{split-out_1.items}}', 'split-out_1', 'items', 'iter_9'),
    '{{iter_9.item}}',
    'plain whole-array rewrites to item',
  );
  nc.assert.equal(
    rewriteListRefsForIteration('{{split-out_1.items[].video_url}}', 'split-out_1', 'items', 'iter_9'),
    '{{iter_9.item.video_url}}',
    '[] map rewrites to item.field',
  );
  nc.assert.equal(
    rewriteListRefsForIteration('{{other.items}}', 'split-out_1', 'items', 'iter_9'),
    '{{other.items}}',
    'a different source is left untouched',
  );
  nc.assert.equal(
    rewriteListRefsForIteration('{{src.items_count}}', 'src', 'items', 'iter_9'),
    '{{src.items_count}}',
    'a sibling field (items_count) is not clobbered',
  );
  // Loop `values`: a literal index becomes the loop var; deeper accessors stay.
  nc.assert.equal(
    rewriteListRefsForIteration('{{sheets.values[5]}}', 'sheets', 'values', 'iter_9'),
    '{{iter_9.item}}',
    'literal index drops (row 5 -> current item)',
  );
  nc.assert.equal(
    rewriteListRefsForIteration('{{sheets.values[8][1]}}', 'sheets', 'values', 'iter_9'),
    '{{iter_9.item[1]}}',
    'outer index loops, inner index stays as per-item accessor',
  );
  nc.assert.equal(
    rewriteListRefsForIteration('{{sheets.values[3].name}}', 'sheets', 'values', 'iter_9'),
    '{{iter_9.item.name}}',
    'field after the looped index is preserved',
  );

  // --- array-output detection (drives the chip + field button) ---
  nc.assert.equal(getNodeArrayOutputPath('split-out', null), 'items', 'split-out emits items pre-run');
  nc.assert.equal(getNodeArrayOutputPath('filter', null), 'filtered', 'filter emits filtered pre-run');
  nc.assert.equal(getNodeArrayOutputPath('automation-rss', null), 'entries', 'rss emits entries pre-run');
  nc.assert.equal(getNodeArrayOutputPath('automation-http', [1, 2]), '', 'root array output');
  nc.assert.equal(
    getNodeArrayOutputPath('x', { values: [[1]], status: 'ok' }),
    'values',
    'sole array field detected at runtime',
  );
  nc.assert.equal(getNodeArrayOutputPath('x', { a: 1 }), null, 'scalar output → no nudge');
  nc.assert.equal(
    getNodeArrayOutputPath('filter', { filtered: { grouped: [1] } }),
    null,
    'known emitter that ran non-array (group-by) → no false nudge',
  );

  return { ok: true };
}
