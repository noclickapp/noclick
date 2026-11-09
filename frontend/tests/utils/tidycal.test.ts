import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/tidycal.json';

describe('TidyCal credential and operations', () => {
    beforeAll(() => loadNodeSchemas(['automation-tidycal']));
    it('offers a personal token that a person can paste', () => {
        expect(getNodeCredentialInfo('automation-tidycal')?.acceptedTypes).toEqual(['tidycal_personal_token']);
        expect(methodFromRequirement(requirementsFromSchema(schema)[0])).toMatchObject({method_kind: 'api_key', is_oauth: false});
        expect(schema.$defs.TidyCalPersonalToken.properties.credential_type.default).toBe('tidycal_personal_token');
    });
    it('exposes 25 contracted reads and writes', () => {
        const ops = getAgentToolOperations('automation-tidycal').map(op => op.operation);
        expect(ops).toHaveLength(25);
        expect(ops).toEqual(expect.arrayContaining(['get_account', 'create_booking', 'cancel_booking', 'reschedule_booking', 'create_contact']));
    });
});
