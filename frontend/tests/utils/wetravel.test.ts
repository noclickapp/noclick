/** Checks that WeTravel offers a manual Partner API key and discoverable actions.
 * Keeps the account connection and publishing wording aligned with the provider contract. */
import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeSchema, getAgentToolOperations } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-wetravel']));
it('connects WeTravel with a manually pasted Partner API key', () => {
    const requirements = requirementsFromSchema(getNodeSchema('automation-wetravel')!);
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0])).toMatchObject({
        credential_type: 'wetravel_partner_api_key', method_kind: 'api_key', is_oauth: false,
    });
});
it('exposes the twelve contract operations', () => {
    const operations = getAgentToolOperations('automation-wetravel');
    expect(operations).toHaveLength(12);
    expect(operations.map(op => op.operation)).toContain('update_trip_itinerary');
    expect(operations.find(op => op.operation === 'create_trip')?.displayName).toMatch(/publish/i);
});
