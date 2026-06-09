import { describe, expect, it } from 'vitest';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import {
    buildNodeSearchIndexEntry,
    getNodeSearchScore,
    getOperationSearchMatch,
} from '~/utils/nodeSearchMatch';

// buildNodeSearchIndexEntry only reads label/description/type off the node and
// pulls everything else from the generated JSON schema, so a minimal stub is a
// faithful stand-in for the real registry entry without importing every node
// component into the test runner.
const redditNode = {
    type: 'automation-reddit',
    label: 'Reddit',
    description: 'Reddit automation',
} as unknown as NodeDefinition;

describe('node palette operation matching', () => {
    const reddit = buildNodeSearchIndexEntry(redditNode);

    it('indexes the node operations', () => {
        // Reddit is a discriminated node with many operations — the index must
        // pick them up or there is nothing to gate.
        expect(reddit.operations.length).toBeGreaterThan(1);
    });

    it('does not seed an operation for a bare node-name query', () => {
        // The regression: "reddit" appears in nearly every operation (via
        // "subreddit" etc.), which used to seed whichever operation came first.
        expect(getOperationSearchMatch(reddit, 'reddit')).toBeNull();
    });

    it('still surfaces the node for a bare node-name query', () => {
        expect(getNodeSearchScore(reddit, 'reddit')).not.toBeNull();
    });

    it('seeds an operation when the query carries operation intent', () => {
        const match = getOperationSearchMatch(reddit, 'get user comments');
        expect(match?.initialOperation).toBe('get_user_comments');
    });

    it('treats the node name plus an operation term as operation intent', () => {
        const match = getOperationSearchMatch(reddit, 'reddit get user comments');
        expect(match?.initialOperation).toBe('get_user_comments');
    });

    it('prefers an operation whose own name matches over a field-metadata hit', () => {
        const match = getOperationSearchMatch(reddit, 'get user posts');
        expect(match?.initialOperation).toBe('get_user_posts');
    });
});

// A second multi-word node guards against the gate being tuned to Reddit:
// the whole node name must be treated as identity, not just a single word.
describe('node palette operation matching — multi-word node identity', () => {
    const sheets = buildNodeSearchIndexEntry({
        type: 'automation-google-sheets',
        label: 'Google Sheets',
        description: 'Google Sheets automation',
    } as unknown as NodeDefinition);

    it('does not seed an operation for the bare node name', () => {
        expect(getOperationSearchMatch(sheets, 'google sheets')).toBeNull();
        expect(getNodeSearchScore(sheets, 'google sheets')).not.toBeNull();
    });

    it('seeds an operation from operation-intent terms', () => {
        expect(getOperationSearchMatch(sheets, 'append rows')?.initialOperation).toBe('append_rows_to_sheet');
        expect(getOperationSearchMatch(sheets, 'google sheets append rows')?.initialOperation).toBe(
            'append_rows_to_sheet',
        );
    });
});
