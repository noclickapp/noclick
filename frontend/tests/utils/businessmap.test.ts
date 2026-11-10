import { beforeAll, expect, it } from 'vitest';
import { BusinessmapNode } from '~/components/workflow/nodes/integrations/businessmap';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-businessmap']));
it('offers a manual Businessmap API key with its account URL', () => {
    expect(BusinessmapNode.category).toBe('productivity');
    const methods = credentialRequirements('automation-businessmap').map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0].credential_type).toBe('businessmap_api_key');
    expect(methods[0].method_kind).toBe('api_key');
    expect(methods[0].is_oauth).toBe(false);
    expect(methods[0].credential_fields.map(field => field.name)).toEqual(['account_url', 'api_key']);
});
