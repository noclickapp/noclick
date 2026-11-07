import { beforeAll, expect, it } from 'vitest';
import schema from '~/schemas/nodes/contabo.json';
import { ContaboNode } from '~/components/workflow/nodes/integrations/contabo';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas([ContaboNode.type]));

it('discovers Contabo and its manually supplied bearer token without an OAuth callback', () => {
    expect(ContaboNode.type).toBe('automation-contabo');
    expect(getNodeCredentialInfo(ContaboNode.type)?.acceptedTypes).toEqual(['contabo_bearer']);
    expect(CREDENTIAL_TYPE_MAP.ContaboBearerCredential).toBe('contabo_bearer');
    expect(CREDENTIAL_TYPE_MAP['Contabo Bearer Token']).toBe('contabo_bearer');
    const methods = credentialRequirements(ContaboNode.type).map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0]).toMatchObject({ credential_type: 'contabo_bearer', method_kind: 'api_key', is_oauth: false });
    expect(schema.$defs.ContaboBearerCredential.properties.access_token['ui:widget']).toBe('password');
    expect(schema.$defs.ContaboBearerCredential.required).toEqual(['access_token']);
});

it('keeps explicit resource IDs, bounded pagination and names opt in', () => {
    expect(schema.$defs.GetInstance.required).toContain('instance_id');
    expect(schema.$defs.GetSnapshot.required).toEqual(expect.arrayContaining(['instance_id', 'snapshot_id']));
    expect(schema.$defs.ListInstances.properties.page.minimum).toBe(1);
    expect(schema.$defs.ListInstances.properties.page_size.maximum).toBe(100);
    expect(schema.$defs.ListInstances.properties.include_names.default).toBe(false);
});
