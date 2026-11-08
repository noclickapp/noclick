// Verify Razorpay's generated credential and operation metadata through shared consumers.
// This guards discovery and manual API-key rendering without a shared registry entry.
import { beforeAll, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/razorpay.json'), 'utf8'));

describe('Razorpay integration metadata', () => {
    beforeAll(() => loadNodeSchemas(['automation-razorpay']));
    it('discovers a manual API-key pair with clear labels and password widgets', () => {
        expect(getNodeCredentialInfo('automation-razorpay')?.acceptedTypes).toEqual(['razorpay_api_key']);
        expect(getCredentialTypeFromSchemaTitle('RazorpayAPIKeyCredential')).toBe('razorpay_api_key');
        expect(getCredentialTypeFromSchemaTitle('Razorpay API Key')).toBe('razorpay_api_key');
        const method = methodFromRequirement(requirementsFromSchema(schema)[0]);
        expect(method.method_kind).toBe('api_key');
        expect(method.credential_fields).toEqual(expect.arrayContaining([
            expect.objectContaining({ name: 'key_id', label: 'Key ID', type: 'password', required: true }),
            expect.objectContaining({ name: 'key_secret', label: 'Key Secret', type: 'password', required: true }),
        ]));
    });
    it('exposes fifteen operations and keeps each operation config separate', () => {
        const operations = getAgentToolOperations('automation-razorpay').map(op => op.operation);
        expect(operations).toHaveLength(15);
        expect(operations).toEqual(expect.arrayContaining(['create_order', 'create_payment_link', 'create_subscription', 'list_customers']));
        expect(filterConfigForExecution('automation-razorpay', { operation: 'list_customers', count: 5, amount: 1000 })).toEqual({ operation: 'list_customers', count: 5 });
    });
});
