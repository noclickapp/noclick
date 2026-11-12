import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { DigitalOceanNode } from '~/components/workflow/nodes/integrations/digitalocean';

beforeAll(async () => { await loadNodeSchemas(['automation-digitalocean']); });
it('offers OAuth and a personal access token under cloud hosting', () => {
    expect(DigitalOceanNode.category).toBe('cloud-hosting');
    expect(getNodeCredentialInfo(DigitalOceanNode.type)?.acceptedTypes).toEqual(
        expect.arrayContaining(['digitalocean_oauth', 'digitalocean_pat']),
    );
    expect(credentialRequirements(DigitalOceanNode.type).map(methodFromRequirement)).toEqual(
        expect.arrayContaining([
            expect.objectContaining({ credential_type: 'digitalocean_oauth', method_kind: 'oauth', is_oauth: true }),
            expect.objectContaining({ credential_type: 'digitalocean_pat', method_kind: 'api_key', is_oauth: false }),
        ]),
    );
});
