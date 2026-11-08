/** Verify the ServiceTitan connect form exposes its manual credential fields. Guards the method kind so a token never opens an unsupported browser OAuth flow. */
import { beforeAll, expect, it } from 'vitest';
import { ServiceTitanNode } from '~/components/workflow/nodes/integrations/servicetitan';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-servicetitan']));
it('offers a manual ServiceTitan token, app key, tenant and environment', () => {
    expect(ServiceTitanNode.type).toBe('automation-servicetitan');
    const methods = credentialRequirements(ServiceTitanNode.type).map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0].method_kind).toBe('api_key');
    expect(methods[0].is_oauth).toBe(false);
    expect(methods[0].credential_fields.map(field => field.name)).toEqual(['access_token', 'app_key', 'tenant_id', 'environment']);
});
