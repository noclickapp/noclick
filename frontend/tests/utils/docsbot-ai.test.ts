import { beforeAll, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { getNodeSchema } from '~/utils/nodeSchemas';

describe('DocsBot AI integration metadata', () => {
    beforeAll(() => loadNodeSchemas(['automation-docsbot-ai']));

    it('offers the pasted API key method with its provider title', () => {
        expect(getNodeCredentialInfo('automation-docsbot-ai')?.acceptedTypes).toEqual(['docsbot_ai_api_key']);
        expect(getCredentialTypeFromSchemaTitle('DocsBot AI API Key')).toBe('docsbot_ai_api_key');
        const schema = getNodeSchema('automation-docsbot-ai');
        expect(schema).toBeDefined();
        expect(methodFromRequirement(requirementsFromSchema(schema!)[0]).method_kind).toBe('api_key');
    });

    it('offers all sixteen operations to the workflow and agent tool pickers', () => {
        const operations = getAgentToolOperations('automation-docsbot-ai').map(op => op.operation);
        expect(operations).toHaveLength(16);
        expect(operations).toContain('list_libraries');
        expect(operations).toContain('chat_agent');
        expect(operations).toContain('capture_lead');
        expect(operations).toContain('cancel_research');
    });
});
