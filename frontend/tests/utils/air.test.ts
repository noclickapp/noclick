import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, NODE_SCHEMAS, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
import { AirNode } from '~/components/workflow/nodes/integrations/air';
beforeAll(() => loadNodeSchemas(['automation-air']));
it('offers a manual API key and discovers actions and polling triggers', () => {
    const schema = NODE_SCHEMAS['automation-air'];
    expect(getNodeCredentialInfo('automation-air')?.acceptedTypes).toEqual(['air_api_key']);
    expect(methodFromRequirement(requirementsFromSchema(schema)[0])).toMatchObject({ method_kind: 'api_key', is_oauth: false });
    expect(Object.keys(schema.properties.config.discriminator.mapping)).toHaveLength(23);
    expect(AirNode.category).toBe('media');
});
