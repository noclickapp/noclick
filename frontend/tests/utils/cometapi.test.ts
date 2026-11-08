import { beforeAll, expect, it } from 'vitest';
import { CometAPINode } from '~/components/workflow/nodes/integrations/cometapi';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-cometapi']));
it('discovers CometAPI with one manually pasted API key', () => {
    expect(CometAPINode.type).toBe('automation-cometapi');
    expect(CometAPINode.category).toBe('ai');
    expect(getNodeCredentialInfo('automation-cometapi')?.label).toBe('Cometapi API Key');
    expect(getNodeCredentialInfo('automation-cometapi')?.acceptedTypes).toEqual(['cometapi_api_key']);
    const methods = credentialRequirements('automation-cometapi').map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0].method_kind).toBe('api_key');
    expect(methods[0].is_oauth).toBe(false);
    expect(methods[0].credential_fields.map(field => field.name)).toEqual(['api_key']);
});
