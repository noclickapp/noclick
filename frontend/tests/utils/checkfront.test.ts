// Verify Checkfront's discovered operations and manual connection form.
// These assertions keep its generated metadata aligned with the provider definition.
import { beforeAll, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/checkfront.json'), 'utf8'));

describe('Checkfront integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-checkfront']));
    it('offers manual token-pair credentials with all three inputs', () => {
        expect(getNodeCredentialInfo('automation-checkfront')?.acceptedTypes).toEqual(['checkfront_api_key']);
        expect(methodFromRequirement(requirementsFromSchema(schema)[0])).toMatchObject({ method_kind: 'api_key', is_oauth: false });
        expect(schema.$defs.CheckfrontAPIKeyCredential.required).toEqual(['tenant_url', 'api_key', 'api_secret']);
        expect(schema.$defs.CheckfrontAPIKeyCredential.properties.credential_type.default).toBe('checkfront_api_key');
    });
    it('discovers 25 documented operations, including writes', () => {
        const operations = getAgentToolOperations('automation-checkfront').map(op => op.operation);
        expect(operations).toHaveLength(25);
        expect(operations).toEqual(expect.arrayContaining(['list_bookings', 'change_booking_status', 'create_customer', 'create_booking_note', 'checkin_booking']));
    });
});
