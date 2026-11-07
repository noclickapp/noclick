// Exercises native generated credential fields, cache selection and saved operation filtering.
// Socket and IndexedDB are local boundaries.
import { afterEach, expect, it, vi } from 'vitest';
import schema from '~/schemas/nodes/adobe-analytics.json';
import { AdobeAnalyticsNode } from '~/components/workflow/nodes/integrations/adobe-analytics';
import { getNodeCredentialInfo, filterConfigForExecution, loadNodeSchemas } from '~/utils/nodeSchemas';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';

const boundary = vi.hoisted(() => ({ send: vi.fn(), get: vi.fn(), set: vi.fn(), delete: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: boundary.send }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: boundary.get, set: boundary.set, delete: boundary.delete } }));
const { invalidateCredentialsCache, removeCredentialsFromCache, upsertCredentialsIntoCache } = await import('~/utils/credentialAutoSelect');
const { autoSelectCredentialFromCache } = await import('~/utils/credentialAutoSelectForNode');
await loadNodeSchemas(['automation-adobe-analytics']);
afterEach(() => { removeCredentialsFromCache(['fixture-owned', 'fixture-foreign']); invalidateCredentialsCache(); });

it('pins the native service and issued-token credential golden contract', () => {
    expect(AdobeAnalyticsNode.type).toBe('automation-adobe-analytics');
    expect(AdobeAnalyticsNode.label).toBe('Adobe Analytics');
    expect(CREDENTIAL_TYPE_MAP.AdobeAnalyticsTokenCredential).toBe('adobe_analytics_token');
    const credential = schema.$defs.AdobeAnalyticsTokenCredential;
    expect(new Set(credential.required)).toEqual(new Set(['access_token', 'client_id', 'global_company_id']));
    expect(credential.properties.credential_type.const).toBe('adobe_analytics_token');
    expect(credential.properties.access_token['ui:widget']).toBe('password');
    expect(credential).not.toHaveProperty('x-oauth-provider');
    expect(getNodeCredentialInfo('automation-adobe-analytics')).toMatchObject({ acceptedTypes: ['adobe_analytics_token'], label: 'Adobe Analytics Access Token' });
});

it('selects owned Analytics credentials through the actual native cache entry', () => {
    invalidateCredentialsCache();
    upsertCredentialsIntoCache([{ id: 'fixture-foreign', name: 'Foreign', credential_type: 'adobe_campaign_token', owned_by_me: true },
        { id: 'fixture-owned', name: 'Analytics', credential_type: 'adobe_analytics_token', owned_by_me: true }]);
    expect(autoSelectCredentialFromCache('automation-adobe-analytics')).toEqual({ adobe_analytics_token: 'fixture-owned' });
    expect(boundary.send).not.toHaveBeenCalled();
});

it('preserves a saved report config and removes a genuine other-operation field', () => {
    const output = filterConfigForExecution('automation-adobe-analytics', { operation: 'run_report', rsid: 'fixturesuite',
        metric_ids: ['metrics/visits'], start: '2026-01-01T00:00:00', end: '2026-01-02T00:00:00',
        confirm_component_deletion: true, label: 'Saved report', _settings: { retryOnFail: 'false' } });
    expect(output).toMatchObject({ operation: 'run_report', rsid: 'fixturesuite', metric_ids: ['metrics/visits'], label: 'Saved report' });
    expect(output).not.toHaveProperty('confirm_component_deletion');
});


it('uses the issued-token method without offering an unsupported OAuth connect flow', () => {
    const methods = credentialRequirements('automation-adobe-analytics').map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0].method_kind).toBe('api_key');
});
