// Verify Vagaro discovery and the generated configuration's native API boundaries.
// These assertions keep token connection details and profile updates aligned with the backend.
import { beforeAll, expect, it, vi } from 'vitest';
import schema from '~/schemas/nodes/vagaro.json';
import { VagaroNode } from '~/components/workflow/nodes/integrations/vagaro';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';

vi.mock('~/components/workflow/nodes/base/AutomationNode', () => ({ default: () => null }));
beforeAll(async () => { await loadNodeSchemas([VagaroNode.type]); });

it('discovers the issued token without offering an OAuth callback', () => {
    expect(VagaroNode.type).toBe('automation-vagaro');
    expect(getNodeCredentialInfo(VagaroNode.type)?.acceptedTypes).toEqual(['vagaro_issued_client_token']);
    const credential = schema.$defs.VagaroIssuedClientTokenCredential;
    expect(credential.title).toBe('Vagaro Issued Client Token');
    expect(credential.properties.access_token['ui:widget']).toBe('password');
    expect(credential.properties.region).toBeDefined();
    expect(credential.properties.granted_scopes.items.enum).toEqual(['read access', 'write access', 'write employee']);
    expect((credential as Record<string, unknown>)['x-oauth-provider']).toBeUndefined();
});

it('declares only the documented profile-update fields', () => {
    const config = schema.$defs.UpdateLocation;
    expect(config.additionalProperties).toBe(false);
    expect(config.properties.acknowledge_profile_effects).toBeDefined();
    for (const key of ['listedOnVagaro', 'businessHours', 'outCallPrice']) expect(config.properties).not.toHaveProperty(key);
    expect(schema.$defs.GetCustomer.properties.business_id['x-dynamic-options'].field_name).toBe('business_id');
    expect(schema.$defs.GetCustomer.properties.include_contact_details.default).toBe(false);
});
