import { describe, expect, it } from 'vitest';
import schema from '../../app/schemas/nodes/circleci.json';
import metadata from '../../app/schemas/nodeMeta/circleci.json';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

describe('CircleCI credentials', () => {
    it('offers a personal token through the existing API-key method', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method.credential_type).toBe('circleci_pat');
        expect(method.method_kind).toBe('api_key');
        expect(method.is_oauth).toBe(false);
        expect(metadata.type).toBe('automation-circleci');
        expect(metadata.autoSelectCredential).toBe(true);
    });
});
