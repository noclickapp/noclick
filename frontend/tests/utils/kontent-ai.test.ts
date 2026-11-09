import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/kontent-ai.json';

describe('Kontent.ai metadata', () => {
    beforeAll(() => loadNodeSchemas(['automation-kontent-ai']));

    it('offers a manually pasted Management API key', () => {
        expect(getNodeCredentialInfo('automation-kontent-ai')?.acceptedTypes).toEqual(['kontent_ai_api_key']);
        expect(getCredentialTypeFromSchemaTitle('Kontent.ai Management API Key')).toBe('kontent_ai_api_key');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    });

    it('discovers content and publishing operations', () => {
        const operations = getAgentToolOperations('automation-kontent-ai').map(op => op.operation);
        expect(operations).toHaveLength(24);
        expect(operations).toContain('update_item');
        expect(operations).toContain('publish_variant');
        expect(operations).toContain('create_language');
    });
});
