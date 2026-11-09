import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/chorus-by-zoominfo.json';

describe('Chorus by ZoomInfo credentials', () => {
    it('discovers a manual personal API token method', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-chorus-by-zoominfo');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'chorus_by_zoominfo_api_token', method_kind: 'api_key', is_oauth: false,
        });
    });
});
