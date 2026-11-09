import { describe, expect, it } from 'vitest';
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/teamwork-desk.json';

describe('Teamwork Desk credentials', () => {
    it('discovers a hand-connectable Desk API key', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-teamwork-desk');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method).toMatchObject({
            credential_type: 'teamwork_desk_api_key',
            method_kind: 'api_key',
            is_oauth: false,
        });
        expect(
            method.credential_fields.map((field) => field.name).sort()
        ).toEqual(['api_key', 'site_url']);
    });
});
