import { beforeAll, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));

import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/reply-io.json';

describe('Reply Io integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-reply-io']));

    it('offers a pasted API key through the shared credential form', () => {
        expect(getNodeCredentialInfo('automation-reply-io')?.acceptedTypes).toEqual(['reply_io_api_key']);
        expect(getCredentialTypeFromSchemaTitle('Reply Io API Key')).toBe('reply_io_api_key');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    });

    it('exposes its operations and keeps configuration specific to the selected action', () => {
        const operations = getAgentToolOperations('automation-reply-io').map(op => op.operation);
        expect(operations).toHaveLength(24);
        expect(operations).toEqual(expect.arrayContaining(['get_current_user', 'create_contact', 'add_contacts_to_sequence', 'complete_task']));
        expect(filterConfigForExecution('automation-reply-io', {
            operation: 'update_contact', contact_id: 123, firstName: 'Jane', task_id: 456,
        })).toEqual({ operation: 'update_contact', contact_id: 123, firstName: 'Jane' });
    });
});
