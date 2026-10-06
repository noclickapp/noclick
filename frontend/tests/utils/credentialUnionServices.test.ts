// Checks the actual service-picker lookup against nested generated credential shapes.
// Test-only registry/type-map entries mirror the provider registrations so this shared fix needs no provider-specific production edits.
import { afterEach, expect, it, vi } from 'vitest';
import { NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { getServiceCredentialOptions, getServiceForCredentialType } from '~/utils/credentialTypes';
import { dripCredentialSchema, mauticCredentialSchema } from '../fixtures/credentialUnionSchemas';

vi.mock('~/components/workflow/nodes/nodeRegistry', () => ({ AVAILABLE_NODES: [
    { type: 'automation-drip-union-fixture', label: 'Drip', Icon: () => null },
    { type: 'automation-mautic-union-fixture', label: 'Mautic', Icon: () => null },
] }));

const providerMappings: Record<string, string> = {
    'Drip OAuth': 'drip_oauth', 'Drip API Token': 'drip_api_token',
    MauticBasicCredential: 'mautic_basic', MauticOAuth2Credential: 'mautic_oauth2',
};
const previousMappings = Object.fromEntries(Object.keys(providerMappings).map(key => [key, CREDENTIAL_TYPE_MAP[key]]));
afterEach(() => {
    delete NODE_SCHEMAS['automation-drip-union-fixture'];
    delete NODE_SCHEMAS['automation-mautic-union-fixture'];
    for (const [key, previous] of Object.entries(previousMappings)) {
        if (previous === undefined) delete CREDENTIAL_TYPE_MAP[key];
        else CREDENTIAL_TYPE_MAP[key] = previous;
    }
});

it('exposes both registered provider methods and reverse lookups in the real picker helper', async () => {
    NODE_SCHEMAS['automation-drip-union-fixture'] = dripCredentialSchema;
    NODE_SCHEMAS['automation-mautic-union-fixture'] = mauticCredentialSchema;
    Object.assign(CREDENTIAL_TYPE_MAP, providerMappings);
    expect(getServiceCredentialOptions()).toEqual([]);
    await vi.dynamicImportSettled();
    const options = getServiceCredentialOptions();
    expect(options.map(option => [option.label, option.primaryCredentialType, option.acceptedCredentialTypes])).toEqual([
        ['Drip', 'drip_oauth', ['drip_oauth', 'drip_api_token']],
        ['Mautic', 'mautic_basic', ['mautic_basic', 'mautic_oauth2']],
    ]);
    expect(getServiceForCredentialType('drip_api_token')?.value).toBe('automation-drip-union-fixture');
    expect(getServiceForCredentialType('mautic_oauth2')?.value).toBe('automation-mautic-union-fixture');
});
