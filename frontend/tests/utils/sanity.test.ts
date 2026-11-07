import { beforeAll, expect, it } from 'vitest';
import { SanityNode } from '~/components/workflow/nodes/integrations/sanity';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-sanity']));

it('discovers Sanity and offers the project robot token as a typed credential', () => {
    expect(SanityNode.type).toBe('automation-sanity');
    expect(SanityNode.label).toBe('Sanity');
    expect(CREDENTIAL_TYPE_MAP.SanityRobotTokenCredential).toBe('sanity_robot_token');
    expect(CREDENTIAL_TYPE_MAP['Sanity Robot Token']).toBe('sanity_robot_token');
    expect(getNodeCredentialInfo('automation-sanity')?.acceptedTypes).toEqual(['sanity_robot_token']);
    const methods = credentialRequirements('automation-sanity').map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0].method_kind).toBe('api_key');
    expect(methods[0].is_oauth).toBe(false);
    expect(methods[0].credential_fields.map(field => field.name)).toEqual(['project_id', 'api_token']);
});
