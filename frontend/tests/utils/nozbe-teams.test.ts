import { expect, it } from 'vitest';
import schema from '~/schemas/nodes/nozbe-teams.json';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

it('offers a pasted Nozbe Teams API token', () => {
    const requirements = requirementsFromSchema(schema);
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
});
