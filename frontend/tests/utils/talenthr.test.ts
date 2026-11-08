import { beforeAll, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, getNodeSchema } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

describe('TalentHR integration metadata', () => {
    beforeAll(() => loadNodeSchemas(['automation-talenthr']));
    it('discovers the API key credential and manual connection method', () => {
        expect(getNodeCredentialInfo('automation-talenthr')?.acceptedTypes).toEqual(['talenthr_api_key']);
        expect(getCredentialTypeFromSchemaTitle('TalenthrApiKeyCredential')).toBe('talenthr_api_key');
        expect(getCredentialTypeFromSchemaTitle('TalentHR API Key')).toBe('talenthr_api_key');
        const schema = getNodeSchema('automation-talenthr');
        expect(schema).toBeTruthy();
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    });
    it('offers 20 bounded employee, organization and leave operations', () => {
        const operations = getAgentToolOperations('automation-talenthr').map(op => op.operation);
        expect(operations).toHaveLength(20);
        expect(operations).toEqual(expect.arrayContaining(['hire_employee', 'update_employee', 'terminate_employee', 'list_departments', 'get_location', 'list_time_off_requests', 'reply_time_off_request']));
    });
});
