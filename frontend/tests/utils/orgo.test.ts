import { beforeAll, expect, it } from 'vitest';
import { OrgoNode } from '~/components/workflow/nodes/integrations/orgo';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-orgo']));
it('offers Orgo API keys through manual connect in the cloud hosting category', () => {
    expect(OrgoNode.type).toBe('automation-orgo');
    expect(OrgoNode.category).toBe('cloud-hosting');
    const methods = credentialRequirements(OrgoNode.type).map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0]).toMatchObject({ credential_type: 'orgo_api_key', method_kind: 'api_key', is_oauth: false });
    expect(methods[0].credential_fields.map(field => field.name)).toEqual(['api_key']);
});
