import { describe, expect, it } from 'vitest';
import { AIAgentNode } from '~/components/workflow/nodes/AIAgentNode';
import { CometAPINode } from '~/components/workflow/nodes/integrations/cometapi';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { matchAgentQuery } from '~/lib/agentModelMatch';
import {
    buildNodeSearchIndexEntry,
    getAgentQueryScore,
    getNodeSearchScore,
    getOperationSearchMatch,
    type NodeSearchIndexEntry,
} from '~/utils/nodeSearchMatch';
import { loadAllNodeSchemas } from '~/utils/nodeSchemas';

// The subjects read node schemas, which load per type (some at collection time).
await loadAllNodeSchemas();

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

    it('seeds via authored x-keywords (intent phrasing the label lacks)', () => {
        // "get rows" / "get values" share no word with "Read Sheet Data"; the
        // authored x-keywords bridge them, giving FlowHelper palette search the
        // same intent coverage as the in-node OperationPicker.
        expect(getOperationSearchMatch(sheets, 'get rows')?.initialOperation).toBe('read_sheet_data');
        expect(getOperationSearchMatch(sheets, 'get values')?.initialOperation).toBe('read_sheet_data');
    });
});

// The reported regression: a node matched by its own NAME ranked LAST because a
// flat operation boost let any sibling whose operation field metadata merely
// mentioned the term outrank it. These tests pin the band ordering that fixes
// it. Hand-built entries keep the bands deterministic (independent of whatever
// the generated schemas happen to contain).
describe('node palette search ranking bands', () => {
    const nodeNamed = (label: string, type: string): NodeSearchIndexEntry => ({
        label: label.toLowerCase(),
        identityHaystack: `${label} ${type}`.toLowerCase(),
        baseHaystack: `${label} ${label} automation ${type}`.toLowerCase(),
        operations: [],
    });
    // A sibling node whose operation only mentions the query inside field
    // metadata (e.g. Slack's "post" op referencing a subreddit field).
    const siblingWithFieldHit: NodeSearchIndexEntry = {
        ...nodeNamed('Slack', 'automation-slack'),
        operations: [
            { value: 'post', label: 'Post Message', nameHaystack: 'post message post_message', fieldHaystack: 'subreddit reddit target field' },
        ],
    };

    it('ranks a node-name match above a sibling operation field-metadata match', () => {
        const reddit = nodeNamed('Reddit', 'automation-reddit');
        const nameScore = getNodeSearchScore(reddit, 'reddit');
        const fieldMatch = getOperationSearchMatch(siblingWithFieldHit, 'reddit');
        expect(nameScore).not.toBeNull();
        expect(fieldMatch).not.toBeNull();
        expect(nameScore!).toBeGreaterThan(fieldMatch!.score);
    });

    it('rewards an exact node-name query above a partial identity hit', () => {
        const reddit = nodeNamed('Reddit', 'automation-reddit');
        expect(getNodeSearchScore(reddit, 'reddit')!).toBeGreaterThan(getNodeSearchScore(reddit, 'redd')!);
    });

    it('ranks an operation-name match above a node description-only match', () => {
        const opNamed: NodeSearchIndexEntry = {
            ...nodeNamed('Mailer', 'automation-mailer'),
            operations: [
                { value: 'send_invoice', label: 'Send Invoice', nameHaystack: 'send invoice send_invoice', fieldHaystack: 'recipient' },
            ],
        };
        // "invoice" is operation-intent here (not in Mailer's identity).
        const opMatch = getOperationSearchMatch(opNamed, 'invoice');
        // A node whose only "invoice" hit is in its description sits a band lower.
        const descNode: NodeSearchIndexEntry = {
            label: 'billing',
            identityHaystack: 'billing automation-billing',
            baseHaystack: 'billing billing handles invoice records automation-billing',
            operations: [],
        };
        const descScore = getNodeSearchScore(descNode, 'invoice');
        expect(opMatch).not.toBeNull();
        expect(descScore).not.toBeNull();
        expect(opMatch!.score).toBeGreaterThan(descScore!);
    });
});

// Claude, GPT, Gemini and the coding harnesses are picked inside the AI Agent
// node, so its label and description never name them. Its keywords must, or a
// search for a model finds only integrations that happen to mention it.
describe('AI Agent search by the models and harnesses picked inside it', () => {
    const agent = buildNodeSearchIndexEntry(AIAgentNode, false);
    const cometApi = buildNodeSearchIndexEntry(CometAPINode, false);

    it.each(['claude', 'gpt', 'chatgpt', 'gemini', 'deepseek', 'llm', 'chatbot', 'claude code', 'codex', 'openclaw'])(
        'finds the AI Agent for "%s" from its definition alone',
        (query) => {
            expect(getNodeSearchScore(agent, query)).not.toBeNull();
        },
    );

    it('never ranks CometAPI, which also lists claude, above the AI Agent for "claude"', () => {
        const cometScore = getNodeSearchScore(cometApi, 'claude')!;
        expect(cometScore).not.toBeNull();
        // The palette's Agent tile scores a harness query through matchAgentQuery...
        expect(getAgentQueryScore(matchAgentQuery('claude')!)).toBeGreaterThan(cometScore);
        // ...and on the name path a keyword tie sorts by label, AI Agent first.
        expect(getNodeSearchScore(agent, 'claude')!).toBeGreaterThanOrEqual(cometScore);
        expect(AIAgentNode.label.localeCompare(CometAPINode.label)).toBeLessThan(0);
    });
});
