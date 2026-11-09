import { beforeAll, expect, it } from 'vitest';
import { HostfullyNode } from '~/components/workflow/nodes/integrations/hostfully';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-hostfully']));
it('offers a manual Hostfully key, agency UID and environment', () => {
    expect(HostfullyNode.category).toBe('bookings');
    expect(getNodeCredentialInfo('automation-hostfully')?.acceptedTypes).toEqual(['hostfully_api_key']);
    const methods = credentialRequirements('automation-hostfully').map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0].method_kind).toBe('api_key');
    expect(methods[0].is_oauth).toBe(false);
    expect(methods[0].credential_fields.map(field => field.name)).toEqual(['api_key', 'agency_uid', 'environment']);
});
