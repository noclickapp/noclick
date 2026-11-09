import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { SureSendNode } from '../../app/components/workflow/nodes/integrations/sure-send';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-sure-send']);

describe('Sure Send integration', () => {
    it('exposes CRM reads and writes in the CRM catalog', () => {
        expect(SureSendNode.type).toBe('automation-sure-send');
        expect(SureSendNode.category).toBe('crm-sales');
        const operations = getAgentToolOperations('automation-sure-send').map(op => op.operation);
        expect(operations).toHaveLength(25);
        expect(operations).toContain('get_identity');
        expect(operations).toContain('update_person');
        expect(operations).toContain('enroll_in_automation');
        expect(operations).toContain('create_text_message');
        expect(operations).toContain('create_email_message');
    });
    it('offers a pasted token without an OAuth flow', () => {
        const methods = credentialRequirements('automation-sure-send').map(r => methodFromRequirement(r));
        expect(methods.map(m => m.method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-sure-send')?.acceptedTypes).toContain('sure_send_api_token');
    });
});
