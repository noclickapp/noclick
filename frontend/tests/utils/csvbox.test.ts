// Csvbox is a discoverable integration with a manually entered API key pair.
// These checks pin its catalog placement and the credential method people see.
import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { CsvboxNode } from '../../app/components/workflow/nodes/integrations/csvbox';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';
import { humanizeCredentialLabel } from '../../app/utils/credentialLabels';

await loadNodeSchemas(['automation-csvbox']);
describe('Csvbox integration', () => {
    it('publishes its sheet actions in the developer tools catalog', () => {
        expect(CsvboxNode.type).toBe('automation-csvbox');
        expect(CsvboxNode.category).toBe('developer-tools');
        const operations = getAgentToolOperations('automation-csvbox').map(o => o.operation);
        expect(operations).toHaveLength(15);
        expect(operations).toContain('merge_validation_functions');
        expect(operations).toContain('list_sheets');
    });
    it('connects using a readable API key method', () => {
        expect(credentialRequirements('automation-csvbox').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-csvbox')?.acceptedTypes).toContain('csvbox_api_key');
        expect(humanizeCredentialLabel('Csvbox API Key')).toBe('Csvbox API Key');
    });
});
