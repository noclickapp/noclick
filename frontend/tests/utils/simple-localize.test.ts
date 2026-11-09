import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { SimpleLocalizeNode } from '../../app/components/workflow/nodes/integrations/simple-localize';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-simple-localize']);
describe('SimpleLocalize integration', () => {
    it('discovers its category and read/write operations', () => {
        expect(SimpleLocalizeNode.category).toBe('developer-tools');
        const operations = getAgentToolOperations(SimpleLocalizeNode.type).map(o => o.operation);
        expect(operations).toHaveLength(21);
        expect(operations).toContain('get_project');
        expect(operations).toContain('update_translation');
        expect(operations).toContain('create_translation_key');
        expect(operations).toContain('delete_language');
    });
    it('offers a manually pasted project API key', () => {
        expect(credentialRequirements(SimpleLocalizeNode.type).map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo(SimpleLocalizeNode.type)?.acceptedTypes).toContain('simple_localize_api_key');
    });
});
