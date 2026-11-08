import { beforeAll, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/ipinfo-io.json'), 'utf8'));

describe('IPinfo Io integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-ipinfo-io']));
    it('discovers the pasted token and its manual connection method', () => {
        expect(getNodeCredentialInfo('automation-ipinfo-io')?.acceptedTypes).toEqual(['ipinfo_io_api_token']);
        expect(getNodeCredentialInfo('automation-ipinfo-io')?.label).toBe('Ipinfo API Token');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
        expect(getCredentialTypeFromSchemaTitle('IpinfoIoTokenCredential')).toBe('ipinfo_io_api_token');
        expect(getCredentialTypeFromSchemaTitle('Ipinfo API Token')).toBe('ipinfo_io_api_token');
    });
    it('exposes twenty published intelligence and report operations', () => {
        expect(getAgentToolOperations('automation-ipinfo-io')).toHaveLength(20);
    });
});
