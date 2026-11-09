import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { InvoiceXpressNode } from '~/components/workflow/nodes/integrations/invoicexpress';

beforeAll(async () => { await loadNodeSchemas(['automation-invoicexpress']); });
it('discovers InvoiceXpress finance actions and a manual API key connection', () => {
    expect(InvoiceXpressNode.category).toBe('finance-accounting');
    expect(getNodeCredentialInfo(InvoiceXpressNode.type)?.acceptedTypes).toEqual(['invoicexpress_api_key']);
    expect(credentialRequirements(InvoiceXpressNode.type).map(methodFromRequirement)).toEqual([
        expect.objectContaining({ credential_type: 'invoicexpress_api_key', method_kind: 'api_key', is_oauth: false }),
    ]);
    const operations = getAgentToolOperations(InvoiceXpressNode.type).map(op => op.operation);
    expect(operations).toHaveLength(22);
    expect(operations).toEqual(expect.arrayContaining(['list_clients', 'create_invoice', 'send_invoice_email', 'generate_payment', 'update_item']));
});
