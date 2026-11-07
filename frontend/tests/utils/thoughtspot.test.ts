// Checks ThoughtSpot's generated credential form and actual canvas selection.
// Uses the native owned-credential cache and execution filter with no account,
// socket or provider calls.
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import thoughtspotSchema from '~/schemas/nodes/thoughtspot.json';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { NODE_SCHEMAS, filterConfigForExecution, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';

const boundary = vi.hoisted(() => ({ send: vi.fn(), get: vi.fn(), set: vi.fn(), delete: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: boundary.send }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: boundary.get, set: boundary.set, delete: boundary.delete } }));
const { invalidateCredentialsCache, removeCredentialsFromCache, upsertCredentialsIntoCache } = await import('~/utils/credentialAutoSelect');
const { autoSelectCredentialFromCache } = await import('~/utils/credentialAutoSelectForNode');

afterEach(() => {
    removeCredentialsFromCache(['thoughtspot-owned', 'thoughtspot-other-owner']);
    invalidateCredentialsCache();
    vi.clearAllMocks();
});

describe('native ThoughtSpot wiring', () => {
    beforeAll(() => loadNodeSchemas(['automation-thoughtspot']));
    it('uses the actual required token form and supplied-token family', () => {
        expect(NODE_SCHEMAS['automation-thoughtspot']).toBe(thoughtspotSchema);
        const credential: any = thoughtspotSchema.$defs.ThoughtSpotAccessTokenCredential;
        expect(credential.required).toEqual(['base_url', 'access_token', 'org_id']);
        expect(credential.properties.credential_type.const).toBe('thoughtspot_access_token');
        expect(credential.properties.access_token['ui:widget']).toBe('password');
        expect(credential['x-oauth-provider']).toBeUndefined();
        expect(CREDENTIAL_TYPE_MAP.ThoughtSpotAccessTokenCredential).toBe('thoughtspot_access_token');
        const info = getNodeCredentialInfo('automation-thoughtspot');
        expect(info?.label).toBe('ThoughtSpot');
        const methods = requirementsFromSchema(thoughtspotSchema).map(methodFromRequirement);
        expect(methods.map(method => method.method_kind)).toEqual(['api_key']);
    });

    it('selects only the actual owned credential without socket work', () => {
        invalidateCredentialsCache();
        upsertCredentialsIntoCache([
            { id: 'thoughtspot-other-owner', name: 'Someone else', credential_type: 'thoughtspot_access_token', owned_by_me: false },
        ]);
        expect(autoSelectCredentialFromCache('automation-thoughtspot')).toEqual({});
        upsertCredentialsIntoCache([
            { id: 'thoughtspot-owned', name: 'Owned fixture', credential_type: 'thoughtspot_access_token', owned_by_me: true },
        ]);
        expect(autoSelectCredentialFromCache('automation-thoughtspot')).toEqual({ thoughtspot_access_token: 'thoughtspot-owned' });
        expect(boundary.send).not.toHaveBeenCalled();
        expect(boundary.get).not.toHaveBeenCalled();
    });

    it('keeps current saved canvas metadata and strips non-selected query fields', () => {
        const filtered = filterConfigForExecution('automation-thoughtspot', {
            operation: 'get_current_user', label: 'Current user', _settings: { retryOnFail: 'false' },
            query_string: '[sales]', data_source_id: '10000000-0000-4000-8000-000000000001',
            confirm_delete: true,
        });
        expect(filtered).toMatchObject({ operation: 'get_current_user', label: 'Current user', _settings: { retryOnFail: 'false' } });
        expect(filtered.query_string).toBeUndefined();
        expect(filtered.data_source_id).toBeUndefined();
        expect(filtered.confirm_delete).toBeUndefined();
    });
});
