import { beforeAll, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));

import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/flutterwave.json';

describe('Flutterwave integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-flutterwave']));

    it('offers the manual access token credential with explicit expiry instructions', () => {
        expect(getNodeCredentialInfo('automation-flutterwave')?.acceptedTypes).toEqual(['flutterwave_access_token']);
        expect(getCredentialTypeFromSchemaTitle('Flutterwave Access Token')).toBe('flutterwave_access_token');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
        expect(JSON.stringify(schema)).toContain('10 minutes');
    });

    it('exposes the reviewed operations and only the selected operation fields', () => {
        expect(getAgentToolOperations('automation-flutterwave')).toHaveLength(24);
        expect(filterConfigForExecution('automation-flutterwave', {
            operation: 'get_customer', id: 'cus-owned', amount: 100, reason: 'duplicate',
        })).toEqual({ operation: 'get_customer', id: 'cus-owned' });
    });
});
