// Checks Heartbeat metadata used by the shared credential form. A pasted API key
// must remain a manual connection with the generated provider label.
import { beforeAll, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-heartbeat']));
it('offers a manual Heartbeat API key', () => {
    const [requirement] = credentialRequirements('automation-heartbeat');
    expect(requirement.label).toBe('Heartbeat API Key');
    expect(methodFromRequirement(requirement).method_kind).toBe('api_key');
});
