import { beforeAll, expect, it } from 'vitest';
import { ZigpollNode } from '~/components/workflow/nodes/integrations/zigpoll';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-zigpoll']));
it('discovers Zigpoll and offers its pasted private key', () => {
    expect(ZigpollNode.type).toBe('automation-zigpoll');
    const methods = credentialRequirements(ZigpollNode.type).map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0].credential_type).toBe('zigpoll_api_key');
    expect(methods[0].method_kind).toBe('api_key');
    expect(methods[0].is_oauth).toBe(false);
    expect(methods[0].credential_fields.map(field => field.name)).toEqual(['api_key']);
});
