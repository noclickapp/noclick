import { beforeAll, expect, it } from 'vitest';
import { DigicertNode } from '~/components/workflow/nodes/integrations/digicert';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
beforeAll(() => loadNodeSchemas(['automation-digicert']));
it('offers a manually pasted key for Content Trust Manager', () => {
    expect(DigicertNode.category).toBe('developer-tools');
    const methods = credentialRequirements('automation-digicert').map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0].method_kind).toBe('api_key');
    expect(methods[0].is_oauth).toBe(false);
    expect(methods[0].credential_fields.map(field => field.name)).toEqual(['api_key', 'host']);
});
