// BuiltWith editor schema and credential selection.
// Storage and socket boundaries are local mocks, while production form/selection helpers are used.
// The schema is generated from the self-registering node.
import { beforeAll, expect, it, vi } from 'vitest';
import schema from '~/schemas/nodes/builtwith.json';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { loadNodeSchemas, filterConfigForExecution, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn(() => { throw new Error('No socket expected'); }) }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(async () => null), set: vi.fn(async () => undefined) } }));

beforeAll(async () => { await loadNodeSchemas(['automation-builtwith']); });

it('exposes one documented operation, bounded domains and a private API key form', () => {
    const definitions = schema.$defs;
    expect(definitions.LookupDomainTechnologies.properties.operation.const).toBe('lookup_domain_technologies');
    expect(definitions.LookupDomainTechnologies.properties.domains.maxItems).toBe(16);
    expect(definitions.LookupDomainTechnologies.required).toContain('domains');
    expect(definitions.BuiltWithApiKeyCredential.required).toEqual(['api_key']);
    expect(definitions.BuiltWithApiKeyCredential.properties.api_key['ui:widget']).toBe('password');
    expect(definitions.BuiltWithApiKeyCredential).not.toHaveProperty('x-oauth-provider');
    expect(getNodeCredentialInfo('automation-builtwith')).toEqual({
        providerKey: 'builtwith', acceptedTypes: ['builtwith_api_key'], label: 'BuiltWith API Key',
    });
    expect(JSON.stringify(definitions.LookupDomainTechnologies)).not.toContain('x-dynamic-options');
});

it('selects only the owned native key and never an injected collaborator descriptor', () => {
    const own = 'fixture-builtwith-own';
    const foreign = 'fixture-builtwith-owner';
    upsertCredentialsIntoCache([{ id: own, credential_type: 'builtwith_api_key', name: 'Owned key', owned_by_me: true }]);
    upsertCredentialsIntoCache([{ id: foreign, credential_type: 'builtwith_api_key', name: 'Flow owner key' }]);
    expect(autoSelectCredentialFromCache('automation-builtwith')).toEqual({ builtwith_api_key: own });
    removeCredentialsFromCache([own, foreign]);
});

it('filters the real saved form while retaining actual canvas metadata', () => {
    const result = filterConfigForExecution('automation-builtwith', {
        operation: 'lookup_domain_technologies', domains: ['example.com'], details: 'names_only',
        bulk_job_id: 'not-an-operation-field', label: 'Technology lookup', _settings: { retryOnFail: 'false' },
    });
    expect(result.domains).toEqual(['example.com']);
    expect(result.details).toBe('names_only');
    // Staging retains unknown sidecars; provider-specific config validation is backend-owned.
    expect(result.bulk_job_id).toBe('not-an-operation-field');
    expect(result.label).toBe('Technology lookup');
    expect(result._settings).toEqual({ retryOnFail: 'false' });
});
