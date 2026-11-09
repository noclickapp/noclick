import { describe, expect, it } from 'vitest';
import {
    credentialRequirements,
    getFieldsFromSchema,
    methodFromRequirement,
} from '~/components/credential/credentialMethods';
import { QontoNode } from '../../app/components/workflow/nodes/integrations/qonto';
import {
    getAgentToolOperations,
    getNodeCredentialInfo,
    loadNodeSchemas,
} from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-qonto']);

describe('Qonto integration', () => {
    it('discovers the finance category and 23 account, transaction and bookkeeping operations', () => {
        expect(QontoNode.category).toBe('finance-accounting');
        const operations = getAgentToolOperations('automation-qonto').map(
            (op) => op.operation
        );
        expect(operations).toHaveLength(23);
        expect(operations).toEqual(
            expect.arrayContaining([
                'get_organization',
                'list_transactions',
                'create_client',
                'create_product',
                'mark_supplier_invoice_as_paid',
            ])
        );
    });

    it('offers one manually entered API key method', () => {
        const requirements = credentialRequirements('automation-qonto');
        expect(
            requirements.map((r) => methodFromRequirement(r).method_kind)
        ).toEqual(['api_key']);
        expect(
            getNodeCredentialInfo('automation-qonto')?.acceptedTypes
        ).toContain('qonto_api_key');
        expect(
            getFieldsFromSchema(requirements[0].schema).map(
                (field) => field.name
            )
        ).toEqual(['login', 'secret_key']);
    });
});
