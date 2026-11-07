import { describe, expect, it } from 'vitest';
import { upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import schema from '~/schemas/nodes/bill.json';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

describe('BILL credential selection on canvas add', () => {
    it('selects the saved AP/AR session from the node schema', async () => {
        await loadNodeSchemas(['automation-bill']);
        expect(getNodeCredentialInfo('automation-bill')).toEqual({
            providerKey: 'bill', acceptedTypes: ['bill_session'], label: 'BILL AP/AR Session',
        });
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
        upsertCredentialsIntoCache([{
            id: 'bill-test-credential',
            name: 'BILL sandbox',
            credential_type: 'bill_session',
            owned_by_me: true,
        }]);

        expect(autoSelectCredentialFromCache('automation-bill')).toEqual({
            bill_session: 'bill-test-credential',
        });
    });
});
