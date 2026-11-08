import { expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
import { loadAllNodeSchemas } from '~/utils/nodeSchemas';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
await loadAllNodeSchemas();
it('offers the eSputnik API key as a manual credential', () => {
    const methods = credentialRequirements('automation-esputnik').map(req => methodFromRequirement(req));
    expect(methods).toHaveLength(1);
    expect(methods[0]).toMatchObject({ credential_type: 'esputnik_api_key', method_kind: 'api_key', is_oauth: false });
});
