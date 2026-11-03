// Pins how node-palette search finds the AI Agent step by coding-agent name:
// exact harness names top the palette, a harness name with one typo still finds
// the Agent but ranks under every literal node-name match, and short or
// unrelated queries leave it out.
import { describe, expect, it } from 'vitest';
import { CloudflareNode } from '~/components/workflow/nodes/CloudflareNode';
import { GoogleCloudStorageNode } from '~/components/workflow/nodes/GoogleCloudStorageNode';
import type { NodeSearchIndexEntry } from '~/utils/nodeSearchMatch';
import { matchAgentQuery } from '~/lib/agentModelMatch';
import {
    buildNodeSearchIndexEntry,
    getAgentQueryScore,
    getNodeSearchScore,
} from '~/utils/nodeSearchMatch';

const model = (q: string) => matchAgentQuery(q)?.config.model ?? null;

describe('matchAgentQuery — harness names', () => {
    it.each([
        ['claude', 'claude-code'],
        ['claude code', 'claude-code'],
        ['codex', 'codex'],
        ['hermes', 'hermes'],
        ['openclaw', 'openclaw'],
        ['open claw', 'openclaw'],
        ['opencode', 'opencode'],
        ['open co', 'opencode'],
    ])('"%s" is an exact match for %s', (q, expected) => {
        const match = matchAgentQuery(q);
        expect(match?.config.model).toBe(expected);
        expect(match?.typo).toBe(false);
    });

    it.each([
        ['cloude', 'claude-code'],
        ['clude', 'claude-code'],
        ['clou', 'claude-code'],
        ['cloud', 'claude-code'],
        ['clude code', 'claude-code'],
        ['cladu', 'claude-code'],
        ['hermis', 'hermes'],
        ['opnclaw', 'openclaw'],
    ])('"%s" is one typo from %s', (q, expected) => {
        const match = matchAgentQuery(q);
        expect(match?.config.model).toBe(expected);
        expect(match?.typo).toBe(true);
    });

    it('forgives no typo under four letters, keeping the three-letter prefix rule', () => {
        expect(model('cl')).toBeNull();
        expect(model('clo')).toBeNull();
        expect(model('op')).toBeNull();
        expect(model('cla')).toBe('claude-code');
        expect(model('ope')).toBe('opencode');
    });

    it('forgives one typo, not two', () => {
        // Two edits from "claude", but one from "code" (Codex): the nearest harness wins.
        expect(model('clode')).toBe('codex');
        expect(model('cluode')).toBeNull();
    });

    it('leaves unrelated queries alone, including one-edit words with another first letter', () => {
        expect(model('slack')).toBeNull();
        expect(model('gmail')).toBeNull();
        expect(model('node')).toBeNull(); // one edit from "code"
        expect(model('term')).toBeNull(); // one edit from "herm"
    });
});

describe('Agent tile rank in the node palette', () => {
    const cloudflare = buildNodeSearchIndexEntry(CloudflareNode, false);
    const cloudStorage = buildNodeSearchIndexEntry(
        GoogleCloudStorageNode,
        false
    );
    const agentScore = (q: string) => getAgentQueryScore(matchAgentQuery(q)!);

    it('puts an exact harness name above any node-name match', () => {
        expect(agentScore('claude')).toBeGreaterThan(
            getNodeSearchScore(cloudflare, 'cloudflare')!
        );
    });

    it('ranks a typo match under every literal node-name match', () => {
        expect(agentScore('cloud')).toBeLessThan(
            getNodeSearchScore(cloudflare, 'cloud')!
        );
        expect(agentScore('cloud')).toBeLessThan(
            getNodeSearchScore(cloudStorage, 'cloud')!
        );
    });

    it('still ranks a typo match above a node that only mentions the word in its description', () => {
        const describedOnly: NodeSearchIndexEntry = {
            label: 'backups',
            identityHaystack: 'backups automation-backups',
            baseHaystack:
                'backups copies files to cloud storage automation-backups',
            operations: [],
        };
        expect(agentScore('cloud')).toBeGreaterThan(
            getNodeSearchScore(describedOnly, 'cloud')!
        );
    });
});
