/** Hevo registration and saved credential selection fixtures.
 * These inspect forms and selectors using mocked storage. */
import { beforeAll, describe, expect, it, vi } from 'vitest';
import schema from '~/schemas/nodes/hevo.json';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { getAgentToolOperations, getNodeSchema, loadNodeSchemas } from '~/utils/nodeSchemas';
import { isAgentToolProviderType } from '~/utils/nodeMeta';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { HevoNode } from '~/components/workflow/nodes/integrations/hevo';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn(async () => ({ credentials: [] })) }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(async () => null), set: vi.fn(async () => {}), delete: vi.fn() } }));

describe('Hevo native regional workflows', () => {
    beforeAll(() => loadNodeSchemas(["automation-hevo"]));

    it('uses actual native form, seven fixed regions and closed operations', () => {
        expect(getNodeSchema('automation-hevo')).toBe(schema);
        expect(HevoNode.label).toBe('Hevo');
        expect(isAgentToolProviderType('automation-hevo')).toBe(true);
        expect(CREDENTIAL_TYPE_MAP.HevoAPIKeyCredential).toBe('hevo_api_key');
        expect(humanizeCredentialLabel('HevoAPIKey')).toBe('Hevo API Key');
        const credential = schema.$defs.HevoAPIKeyCredential;
        expect(credential.properties.region.enum).toEqual(['us', 'us2', 'eu', 'in', 'asia', 'au', 'us-gcp']);
        expect(credential.required).toEqual(['api_key', 'api_secret', 'region']);
        expect(credential.properties.api_key['ui:widget']).toBe('password');
        expect(credential.properties.api_secret['ui:widget']).toBe('password');
        const operations = getAgentToolOperations('automation-hevo').map(op => op.operation);
        expect(operations).toHaveLength(15);
        expect(operations).toContain('get_pipeline_source');
        expect(operations).toContain('update_pipeline_schedule');
        for (const excluded of ['run_pipeline', 'restart_pipeline_object', 'run_workflow', 'update_source_config', 'create_destination', 'generic_request']) {
            expect(operations).not.toContain(excluded);
        }
    });

    it('selects owned native rows while ignoring unrelated and display-only credentials', async () => {
        const cache = await import('~/utils/credentialAutoSelect');
        const { autoSelectCredentialFromCache } = await import('~/utils/credentialAutoSelectForNode');
        cache.invalidateCredentialsCache();
        cache.setActiveCredentialWorkflow('fixture-workflow');
        await cache.prefetchCredentials();
        cache.upsertCredentialsIntoCache([
            { id: 'wrong', name: 'Other data platform', credential_type: 'airbyte_api_key', owned_by_me: true },
            { id: 'owned', name: 'Hevo Europe', credential_type: 'hevo_api_key', owned_by_me: true },
            { id: 'display', name: 'Display', credential_type: 'hevo_api_key', owned_by_me: false },
        ]);
        expect(autoSelectCredentialFromCache('automation-hevo')).toEqual({ hevo_api_key: 'owned' });
        cache.removeCredentialsFromCache(['owned']);
        expect(autoSelectCredentialFromCache('automation-hevo')).toEqual({});
        cache.removeCredentialsFromCache(['wrong', 'display']);
        cache.setActiveCredentialWorkflow(null);
    });
});
