// Single source of truth for "does this node emit an array, and where?". Used by
// the under-field "Loop over each item" hint to decide when to nudge the user
// toward an Iteration node. Added because NoClick has no implicit per-item
// fan-out — looping is always an explicit Iteration node, so we surface the
// suggestion where an array reference would otherwise be silently consumed once.

import { getValueAtPath } from './listReferences';

// Nodes whose output shape is a known array at a fixed path, knowable WITHOUT a
// run (so the nudge shows the moment the node is on the canvas). '' = the node
// output itself is the array.
const KNOWN_ARRAY_OUTPUT_PATHS: Record<string, string> = {
  'split-out': 'items',
  filter: 'filtered',
  'automation-rss': 'entries',
};

/**
 * The path to a node's array output ('' = root array), or null if it doesn't
 * emit an array. Known emitter types resolve pre-run; everything else is
 * detected from a live/mocked output that is either an array itself or an object
 * with exactly one array-valued field (ambiguous multi-array objects return null).
 * When a known emitter HAS run, the output is still verified so a mode that
 * produced a non-array (e.g. Filter group-by) doesn't get a false nudge.
 */
export function getNodeArrayOutputPath(
  nodeType: string | undefined,
  output: unknown,
): string | null {
  if (nodeType && nodeType in KNOWN_ARRAY_OUTPUT_PATHS) {
    const path = KNOWN_ARRAY_OUTPUT_PATHS[nodeType];
    if (output == null) return path; // not run yet — trust the type
    return Array.isArray(getValueAtPath(output, path)) ? path : null;
  }
  if (Array.isArray(output)) return '';
  if (output && typeof output === 'object') {
    const arrayKeys = Object.keys(output as Record<string, unknown>).filter((k) =>
      Array.isArray((output as Record<string, unknown>)[k]),
    );
    if (arrayKeys.length === 1) return arrayKeys[0];
  }
  return null;
}
