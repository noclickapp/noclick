import { beforeAll, expect, it } from 'vitest';
import { ForcemanagerNode } from '~/components/workflow/nodes/integrations/forcemanager';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-forcemanager']));
it('offers the ForceManager session key through manual connect', () => {
    expect(ForcemanagerNode.type).toBe('automation-forcemanager');
    expect(ForcemanagerNode.category).toBe('crm-sales');
    const methods = credentialRequirements(ForcemanagerNode.type).map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0]).toMatchObject({ credential_type: 'forcemanager_session_key', method_kind: 'api_key', is_oauth: false });
    expect(methods[0].credential_fields.map(field => field.name)).toEqual(['session_key']);
});
