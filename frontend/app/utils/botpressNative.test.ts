/** Prepared native Botpress form, operation and credential-selection fixtures.
 * These unrun fixtures do not establish provider access or a real UI capture. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import schema from '~/schemas/nodes/botpress.json';
import { CREDENTIAL_TYPE_MAP } from './credentialTypeMap';
import { getAgentToolOperations, getNodeSchema } from './nodeSchemas';
import { isAgentToolProviderType } from './nodeMeta';
import { humanizeCredentialLabel } from './credentialLabels';
import { BotpressNode } from '~/components/workflow/nodes/BotpressNode';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn(async () => ({ credentials: [] })) }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(async () => null), set: vi.fn(async () => {}), delete: vi.fn() } }));

describe('Botpress native administration and scoped selection', () => {
    beforeEach(() => vi.resetModules());

    it('registers the actual schema, fourteen operations and existing PAT label', () => {
        expect(getNodeSchema('automation-botpress')).toBe(schema);
        expect(CREDENTIAL_TYPE_MAP.BotpressPATCredential).toBe('botpress_pat');
        expect(BotpressNode.type).toBe('automation-botpress');
        expect(BotpressNode.label).toBe('Botpress');
        expect(humanizeCredentialLabel('BotpressPAT')).toBe('Botpress PAT');
        expect(isAgentToolProviderType('automation-botpress')).toBe(true);
        const operations = getAgentToolOperations('automation-botpress').map(op => op.operation);
        expect(operations).toHaveLength(14);
        expect(operations).toContain('create_table');
        expect(operations).toContain('update_rows');
        expect(operations).not.toContain('send_message');
        expect(operations).not.toContain('predict');
        expect(operations).not.toContain('deploy_bot');
    });

    it('selects the owned PAT and excludes bot keys and display-only credentials', async () => {
        const cache = await import('./credentialAutoSelect');
        cache.invalidateCredentialsCache();
        cache.setActiveCredentialWorkflow('fixture-workflow');
        await cache.prefetchCredentials();
        cache.upsertCredentialsIntoCache([
            { id: 'foreign', name: 'Bot access key', credential_type: 'botpress_bot_key', owned_by_me: true },
            { id: 'owned', name: 'Existing PAT', credential_type: 'botpress_pat', owned_by_me: true },
            { id: 'display', name: 'Collaborator', credential_type: 'botpress_pat', owned_by_me: false },
        ]);
        expect(cache.autoSelectCredentialFromCache('automation-botpress')).toEqual({ botpress_pat: 'owned' });
        cache.removeCredentialsFromCache(['owned']);
        expect(cache.autoSelectCredentialFromCache('automation-botpress')).toEqual({});
        cache.removeCredentialsFromCache(['foreign', 'display']);
        cache.setActiveCredentialWorkflow(null);
    });
});
