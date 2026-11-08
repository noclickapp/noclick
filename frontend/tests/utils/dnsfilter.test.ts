// Checks DNSFilter's discovered metadata and pasted-token connect method.
// The generated form must keep required domain-change notes visible.
import { beforeAll, describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '../../app/schemas/nodes/dnsfilter.json';
import { NODE_SCHEMAS, loadNodeSchemas } from '../../app/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '../../app/utils/credentialTypeMap';

describe('DNSFilter integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-dnsfilter']));
    it('discovers the schema and manual API token method', () => {
        expect(NODE_SCHEMAS['automation-dnsfilter']).toBe(schema);
        expect(CREDENTIAL_TYPE_MAP.DNSFilterAPITokenCredential).toBe('dnsfilter_api_token');
        const method = methodFromRequirement(requirementsFromSchema(schema)[0]);
        expect(method.method_kind).toBe('api_key');
        expect(schema.$defs.DNSFilterAPITokenCredential.title).toBe('DNSFilter API Token');
        expect(schema.$defs.DNSFilterAPITokenCredential.properties.api_token['ui:widget']).toBe('password');
    });
    it('requires the provider-mandated domain note and network organization', () => {
        expect(schema.$defs.RemoveAllowlistDomain.required).toContain('note');
        expect(schema.$defs.AddBlocklistDomain.required).toContain('note');
        expect(schema.$defs.UpdateNetwork.required).toContain('organization_id');
    });
});
