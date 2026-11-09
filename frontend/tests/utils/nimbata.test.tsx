import { beforeAll, expect, it } from 'vitest';
import { NimbataNode } from '~/components/workflow/nodes/integrations/nimbata';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas([NimbataNode.type]));

it('offers a manual API token in the marketing category', () => {
    expect(NimbataNode.category).toBe('marketing');
    expect(getNodeCredentialInfo(NimbataNode.type)?.acceptedTypes).toEqual(['nimbata_api_token']);
    const methods = credentialRequirements(NimbataNode.type).map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0]).toMatchObject({ credential_type: 'nimbata_api_token', method_kind: 'api_key', is_oauth: false });
    expect(methods[0].credential_fields?.map(f => f.name)).toEqual(['api_token']);
});
