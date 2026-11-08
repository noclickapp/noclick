import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/gleap.json';

describe('Gleap metadata', () => {
    beforeAll(() => loadNodeSchemas(['automation-gleap']));
    it('offers a pasted service account token', () => {
        expect(getNodeCredentialInfo('automation-gleap')?.acceptedTypes).toEqual(['gleap_service_account']);
        expect(getCredentialTypeFromSchemaTitle('Gleap Service Account Token')).toBe('gleap_service_account');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    });
    it('exposes the native read and write operations', () => {
        const operations = getAgentToolOperations('automation-gleap').map(op => op.operation);
        expect(operations).toHaveLength(23);
        expect(operations).toContain('list_workflows');
        expect(operations).toContain('send_message');
        expect(operations).toContain('create_webhook');
        expect(getAgentToolOperations('automation-gleap').find(op => op.operation === 'send_message')?.displayName).toBe('Send Message');
    });
});
