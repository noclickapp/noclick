import { beforeAll, expect, it } from 'vitest';
import { MightyNetworksNode } from '~/components/workflow/nodes/integrations/mighty-networks';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-mighty-networks']));

it('discovers both Mighty supplied grants without offering an OAuth connect flow', () => {
    expect(MightyNetworksNode.type).toBe('automation-mighty-networks');
    expect(MightyNetworksNode.label).toBe('Mighty Networks');
    expect(CREDENTIAL_TYPE_MAP.MightyNetworksAPIKeyCredential).toBe('mighty_networks_api_key');
    expect(CREDENTIAL_TYPE_MAP.MightyNetworksSuppliedOAuthCredential).toBe('mighty_networks_supplied_oauth');
    expect(getNodeCredentialInfo('automation-mighty-networks')?.acceptedTypes).toEqual([
        'mighty_networks_api_key', 'mighty_networks_supplied_oauth',
    ]);
    const methods = credentialRequirements('automation-mighty-networks').map(methodFromRequirement);
    expect(methods).toHaveLength(2);
    for (const method of methods) {
        expect(method.method_kind).toBe('api_key');
        expect(method.is_oauth).toBe(false);
    }
    expect(methods[1].credential_fields.map(field => field.name)).toContain('expires_at');
});
