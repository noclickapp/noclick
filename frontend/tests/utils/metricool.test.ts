/** Metricool native form, operation and saved-row selection fixtures.
 * These exercise current schema consumers without claiming browser or account proof. */
import { beforeAll, describe, expect, it, vi } from 'vitest';
import schema from '~/schemas/nodes/metricool.json';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { getAgentToolOperations, getNodeSchema, loadNodeSchemas } from '~/utils/nodeSchemas';
import { isAgentToolProviderType } from '~/utils/nodeMeta';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { MetricoolNode } from '~/components/workflow/nodes/integrations/metricool';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn(async () => ({ credentials: [] })) }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(async () => null), set: vi.fn(async () => {}), delete: vi.fn() } }));

describe('Metricool native brand analytics and unpublished drafts', () => {
    beforeAll(() => loadNodeSchemas(['automation-metricool']));

    it('uses the actual native form and thirteen closed operations', () => {
        expect(getNodeSchema('automation-metricool')).toBe(schema);
        expect(MetricoolNode.label).toBe('Metricool');
        expect(isAgentToolProviderType('automation-metricool')).toBe(true);
        expect(CREDENTIAL_TYPE_MAP.MetricoolAPIKeyCredential).toBe('metricool_api_key');
        expect(humanizeCredentialLabel('MetricoolAPIKey')).toBe('Metricool API Key');
        const credential = schema.$defs.MetricoolAPIKeyCredential;
        expect(credential.required).toEqual(['api_token', 'user_id', 'blog_id']);
        expect(credential.properties.api_token['ui:widget']).toBe('password');
        expect(credential.properties).not.toHaveProperty('base_url');
        const operations = getAgentToolOperations('automation-metricool').map(op => op.operation);
        expect(operations).toHaveLength(13);
        expect(operations).toContain('create_draft');
        expect(operations).toContain('get_social_timeline');
        for (const excluded of ['publish', 'schedule', 'set_auto_publish', 'approve_post', 'send_message', 'normalize_media', 'generic_request']) {
            expect(operations).not.toContain(excluded);
        }
        for (const name of ['MetricoolCreateDraft', 'MetricoolUpdateDraft']) {
            expect((schema.$defs as Record<string, any>)[name].properties).not.toHaveProperty('draft');
            expect((schema.$defs as Record<string, any>)[name].properties).not.toHaveProperty('autoPublish');
        }
    });

    it('selects owned native credentials and refuses unrelated/display-only rows', async () => {
        const cache = await import('~/utils/credentialAutoSelect');
        cache.invalidateCredentialsCache();
        cache.setActiveCredentialWorkflow('fixture-workflow');
        await cache.prefetchCredentials();
        cache.upsertCredentialsIntoCache([
            { id: 'wrong', name: 'Other analytics', credential_type: 'buffer_api_key', owned_by_me: true },
            { id: 'owned', name: 'Metricool', credential_type: 'metricool_api_key', owned_by_me: true },
            { id: 'display', name: 'Display only', credential_type: 'metricool_api_key', owned_by_me: false },
        ]);
        expect(autoSelectCredentialFromCache('automation-metricool')).toEqual({ metricool_api_key: 'owned' });
        cache.removeCredentialsFromCache(['owned']);
        expect(autoSelectCredentialFromCache('automation-metricool')).toEqual({});
        cache.removeCredentialsFromCache(['wrong', 'display']);
        cache.setActiveCredentialWorkflow(null);
    });
});
