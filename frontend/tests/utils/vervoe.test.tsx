import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import schema from '~/schemas/nodes/vervoe.json';
import { VervoeNode, VervoeIcon } from '~/components/workflow/nodes/integrations/vervoe';
import { NODE_SCHEMAS, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { isAgentToolProviderType, isTriggerSource } from '~/utils/nodeMeta';

const boundary = vi.hoisted(() => ({ send: vi.fn(), get: vi.fn(), set: vi.fn(), delete: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: boundary.send }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: boundary.get, set: boundary.set, delete: boundary.delete } }));
const { prefetchCredentials, invalidateCredentialsCache, removeCredentialsFromCache, upsertCredentialsIntoCache } = await import('~/utils/credentialAutoSelect');
const { autoSelectCredentialFromCache } = await import('~/utils/credentialAutoSelectForNode');
beforeAll(() => loadNodeSchemas(['automation-vervoe']));
beforeEach(() => { invalidateCredentialsCache(); vi.clearAllMocks(); boundary.get.mockResolvedValue(undefined); });
afterEach(() => { removeCredentialsFromCache(['vervoe-healthy', 'vervoe-revoked', 'vervoe-owner', 'foreign']); invalidateCredentialsCache(); });

describe('native Vervoe schema, credential selection and exact official asset', () => {
    it('uses the account API token and eleven native operations', () => {
        expect(NODE_SCHEMAS['automation-vervoe']).toBe(schema);
        expect(getNodeCredentialInfo('automation-vervoe')).toEqual({ providerKey: 'vervoe', acceptedTypes: ['vervoe_api_key', 'vervoe_bearer_token'], label: 'Vervoe Connection' });
        expect(credentialRequirements(VervoeNode.type).map(methodFromRequirement).map(m => m.method_kind)).toEqual(['api_key', 'api_key']);
        expect(schema.$defs.VervoeBearerTokenCredential.properties.credential_type.const).toBe('vervoe_bearer_token');
        expect(schema.$defs.VervoeBearerTokenCredential.properties.access_token['ui:widget']).toBe('password');
        expect(schema.$defs.VervoeBearerTokenCredential.required).toEqual(expect.arrayContaining(['access_token']));
        const mapping = schema.properties.config.discriminator.mapping;
        expect(Object.keys(mapping)).toHaveLength(11);
        expect(Object.keys(mapping)).toEqual(expect.arrayContaining(['list_assessments', 'get_application', 'create_folder', 'rename_folder', 'move_assessment_to_folder', 'delete_folder']));
        expect(schema.$defs.Application.properties.candidate_assessment_uuid['x-dynamic-options'].depends_on).toBe('assessment_slug');
        expect(isAgentToolProviderType(VervoeNode.type)).toBe(true);
        expect(isTriggerSource(VervoeNode.type, 'list_assessments')).toBe(false);
    });
    it('selects only healthy owned native credentials from real prefetch/cache', async () => {
        boundary.send.mockResolvedValue({ credentials: [
            { id: 'foreign', name: 'Foreign', credential_type: 'slack_oauth', updated_at: '2026-10-06T12:00:00Z' },
            { id: 'vervoe-revoked', name: 'Revoked', credential_type: 'vervoe_api_key', revoked_at: '2026-10-06T11:00:00Z', updated_at: '2026-10-06T11:00:00Z' },
            { id: 'vervoe-healthy', name: 'Fixture Vervoe', credential_type: 'vervoe_api_key', updated_at: '2026-10-06T10:00:00Z' },
        ] });
        await prefetchCredentials();
        upsertCredentialsIntoCache([{ id: 'vervoe-owner', name: 'Owner descriptor', credential_type: 'vervoe_api_key', owned_by_me: false }]);
        expect(autoSelectCredentialFromCache('automation-vervoe')).toEqual({ vervoe_api_key: 'vervoe-healthy' });
        expect(boundary.send).toHaveBeenCalledTimes(1);
        expect(boundary.send.mock.calls[0][0].event_name).toBe('credential:list');
    });
    it('renders the exact official SVG', () => {
        expect(renderToStaticMarkup(createElement(VervoeIcon))).toContain('/icons/vervoe.svg');
    });
});
