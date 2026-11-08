// Exercises Campaign's generated schema and owned credential selection through native consumers.
// Socket, cache and AutomationNode rendering boundaries are synthetic; provider and canvas proof is deferred.
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import schema from '~/schemas/nodes/adobe-campaign.json';
import { AdobeCampaignNode } from '~/components/workflow/nodes/integrations/adobe-campaign';
import { filterConfigForExecution, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';

const boundary = vi.hoisted(() => ({ send: vi.fn(), get: vi.fn(), set: vi.fn(), delete: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: boundary.send }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: boundary }));
vi.mock('~/components/workflow/nodes/base/AutomationNode', () => ({ default: () => null }));
vi.mock('~/components/workflow/nodes/nodeRegistry', async () => ({ AVAILABLE_NODES: [(await import('~/components/workflow/nodes/integrations/adobe-campaign')).AdobeCampaignNode] }));
const selection = await import('~/utils/credentialAutoSelect');
beforeAll(async () => { await loadNodeSchemas(['automation-adobe-campaign']); });
afterEach(() => { selection.invalidateCredentialsCache(); boundary.send.mockReset(); });

it('discovers supplied Campaign access without inventing an interactive OAuth app', () => {
    expect(getNodeCredentialInfo(AdobeCampaignNode.type)?.acceptedTypes).toEqual(['adobe_campaign_access_token']);
    const credential = schema.$defs.AdobeCampaignAccessTokenCredential;
    expect(credential.required).toEqual(expect.arrayContaining(['tenant_id', 'product_mode', 'api_key', 'access_token', 'expires_at']));
    expect(credential.properties.access_token['ui:widget']).toBe('password');
    expect((credential as Record<string, unknown>)['x-oauth-provider']).toBeUndefined();
    expect(credential.properties).not.toHaveProperty('refresh_token');
    expect(humanizeCredentialLabel('AdobeCampaignAccessToken')).toBe('Adobe Campaign Access Token');
});

it('selects only the current owned Campaign credential family', () => {
    selection.upsertCredentialsIntoCache([
        { id: 'foreign', credential_type: 'adobe_oauth', name: 'Foreign', owned_by_me: true },
        { id: 'owned', credential_type: 'adobe_campaign_access_token', name: 'Owned', owned_by_me: true },
    ]);
    expect(autoSelectCredentialFromCache(AdobeCampaignNode.type)).toEqual({ adobe_campaign_access_token: 'owned' });
    expect(boundary.send).not.toHaveBeenCalled();
});

it('retains typed profile changes and declared custom-resource parents', () => {
    const config = filterConfigForExecution(AdobeCampaignNode.type, { operation: 'update_profile', profile_pkey: '@responseKey', first_name: 'Owned',
        confirm_profile_change: true, service_pkey: '@otherOperation' });
    expect(config).toMatchObject({ operation: 'update_profile', profile_pkey: '@responseKey', first_name: 'Owned', confirm_profile_change: true });
    expect(config).not.toHaveProperty('service_pkey');
    expect(schema.$defs.UpdateProfile.additionalProperties).toBe(false);
    for (const key of ['blackList', 'subscribe', 'delivery', 'endpoint']) expect(schema.$defs.UpdateProfile.properties).not.toHaveProperty(key);
    expect(schema.$defs.CustomRecord.properties.resource_name['x-dynamic-options'].depends_on).toBe('resource_api');
    expect(schema.$defs.CustomRecord.properties.record_pkey['x-dynamic-options'].depends_on).toBe('resource_name');
    expect(schema.$defs.Profiles.properties.page_size.maximum).toBe(100);
});
