import { expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
import { loadAllNodeSchemas } from '~/utils/nodeSchemas';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { getProviderConfigByCredentialType } from '~/utils/oauthProviders';
await loadAllNodeSchemas();
it('offers the declared Clio OAuth sign-in', () => {
    expect(credentialRequirements('automation-clio').map(req => methodFromRequirement(req).method_kind)).toEqual(['oauth']);
    expect(getProviderConfigByCredentialType('clio_oauth')).toBeDefined();
});
