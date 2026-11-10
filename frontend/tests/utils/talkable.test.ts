// Talkable metadata and credential-selection regression coverage. This ensures the provider is discovered without edits to shared registries.
import { describe, expect, it, vi } from 'vitest';
import schema from '~/schemas/nodes/talkable.json';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { getAgentToolOperations, getNodeSchema, loadNodeSchemas } from '~/utils/nodeSchemas';
import { isAgentToolProviderType } from '~/utils/nodeMeta';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { kindFromCredentialType } from '~/lib/credentialMethodKind';
import { TalkableNode } from '~/components/workflow/nodes/integrations/talkable';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn(async () => ({ credentials: [] })) }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(async () => null), set: vi.fn(async () => {}), delete: vi.fn() } }));

describe('Talkable native UI and current credential selection', () => {

    it('uses the same native schema in the form, provider tools and slim metadata', async () => {
        await loadNodeSchemas(['automation-talkable']);
        expect(getNodeSchema('automation-talkable')).toBe(schema);
        expect(CREDENTIAL_TYPE_MAP.TalkableApiKeyCredential).toBe('talkable_api_key');
        expect(TalkableNode.type).toBe('automation-talkable');
        expect(TalkableNode.label).toBe('Talkable');
        expect(humanizeCredentialLabel('TalkableApiKey')).toBe('Talkable API Key');
        expect(isAgentToolProviderType('automation-talkable')).toBe(true);
        const operations = getAgentToolOperations('automation-talkable').map(op => op.operation);
        expect(operations).toHaveLength(11);
        expect(operations).toContain('upsert_person_metadata');
        expect(operations).not.toContain('approve_referral');
        expect(operations).not.toContain('create_reward');
    });

    it('identifies the manual API key method', () => {
        expect(kindFromCredentialType('talkable_api_key')).toBe('api_key');
    });
});
