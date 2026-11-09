import { beforeAll, expect, it } from 'vitest';
import { ShipmondoNode } from '~/components/workflow/nodes/integrations/shipmondo';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-shipmondo']));

it('discovers Shipmondo with a manually pasted API user and key', () => {
    expect(ShipmondoNode.type).toBe('automation-shipmondo');
    expect(ShipmondoNode.category).toBe('ecommerce');
    expect(getNodeCredentialInfo('automation-shipmondo')?.label).toBe('Shipmondo API Key');
    expect(getNodeCredentialInfo('automation-shipmondo')?.acceptedTypes).toEqual(['shipmondo_api_key']);
    const methods = credentialRequirements('automation-shipmondo').map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0].method_kind).toBe('api_key');
    expect(methods[0].is_oauth).toBe(false);
    expect(methods[0].credential_fields.map(field => field.name)).toEqual(['api_username', 'api_key']);
});
