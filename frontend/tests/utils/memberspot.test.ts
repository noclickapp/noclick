import { beforeAll, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, isAgentToolProviderType } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/memberspot.json';

describe('Memberspot integration metadata', () => {
    beforeAll(() => loadNodeSchemas(['automation-memberspot']));
    it('offers a labeled pasted API key through native consumers', () => {
        expect(getNodeCredentialInfo('automation-memberspot')?.acceptedTypes).toEqual(['memberspot_api_key']);
        expect(getNodeCredentialInfo('automation-memberspot')?.label).toBe('Memberspot API Key');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
        expect(getCredentialTypeFromSchemaTitle('MemberspotAPIKeyCredential')).toBe('memberspot_api_key');
        expect(getCredentialTypeFromSchemaTitle('Memberspot API Key')).toBe('memberspot_api_key');
    });
    it('exposes 25 read and write operations to agent tools', () => {
        const ops = getAgentToolOperations('automation-memberspot').map(op => op.operation);
        expect(ops).toHaveLength(25);
        expect(ops).toContain('list_courses');
        expect(ops).toContain('grant_offer_by_email');
        expect(ops).toContain('set_offer_expiration');
        expect(isAgentToolProviderType('automation-memberspot')).toBe(true);
    });
});
