import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { AnyDbNode } from '../../app/components/workflow/nodes/integrations/any-db';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-any-db']);
describe('AnyDb integration', () => {
    it('discovers record, file, sharing and webhook operations', () => {
        expect(AnyDbNode.type).toBe('automation-any-db');
        const operations = getAgentToolOperations('automation-any-db').map(o => o.operation);
        expect(operations).toHaveLength(20);
        expect(operations).toContain('list_teams');
        expect(operations).toContain('create_record');
        expect(operations).toContain('register_webhook');
    });
    it('offers a pasted API key and account email', () => {
        expect(credentialRequirements('automation-any-db').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-any-db')?.acceptedTypes).toContain('any_db_api_key');
    });
});
