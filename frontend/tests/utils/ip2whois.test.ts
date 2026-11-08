import { beforeAll, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/ip2whois.json'), 'utf8'));

describe('IP2WHOIS integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-ip2whois']));
    it('discovers the API key with a human label and manual connect method', () => {
        expect(getNodeCredentialInfo('automation-ip2whois')?.acceptedTypes).toEqual(['ip2whois_api_key']);
        expect(getNodeCredentialInfo('automation-ip2whois')?.label).toBe('IP2WHOIS API Key');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
        expect(getCredentialTypeFromSchemaTitle('Ip2WhoisAPIKey')).toBe('ip2whois_api_key');
        expect(getCredentialTypeFromSchemaTitle('IP2WHOIS API Key')).toBe('ip2whois_api_key');
    });
    it('exposes the one published WHOIS operation', () => {
        expect(getAgentToolOperations('automation-ip2whois').map(op => op.operation)).toEqual(['lookup_domain']);
    });
});
