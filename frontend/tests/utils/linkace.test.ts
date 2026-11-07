import { beforeAll, expect, it } from 'vitest';
import { LinkAceNode } from '~/components/workflow/nodes/integrations/linkace';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-linkace']));
it('discovers LinkAce with an existing user token and explicit instance origin', () => {
    expect(LinkAceNode.type).toBe('automation-linkace');
    expect(getNodeCredentialInfo('automation-linkace')?.label).toBe('LinkAce');
    expect(getNodeCredentialInfo('automation-linkace')?.acceptedTypes).toEqual(['linkace_user_token']);
    const methods = credentialRequirements('automation-linkace').map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0].method_kind).toBe('api_key');
    expect(methods[0].is_oauth).toBe(false);
    expect(methods[0].credential_fields.map(field => field.name)).toEqual(['access_token', 'instance_url']);
});
