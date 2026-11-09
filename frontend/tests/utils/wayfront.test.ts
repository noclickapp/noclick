// Verifies Wayfront exposes a hand-filled workspace and API token connection.
// Keeps its discovered credential metadata aligned with the connect UI.
import { describe, expect, it } from 'vitest';
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/wayfront.json';
import meta from '~/schemas/nodeMeta/wayfront.json';

describe('Wayfront manual connection', () => {
    it('exposes the workspace URL and a pasted API token', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map((req) => req.credential_type)).toEqual([
            'wayfront_api_token',
        ]);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe(
            'api_key'
        );
        expect(schema.$defs.WayfrontTokenCredential.required).toEqual([
            'workspace_url',
            'api_token',
        ]);
        expect(
            schema.$defs.WayfrontTokenCredential.properties.credential_type
                .default
        ).toBe('wayfront_api_token');
        expect(meta.credentialTypes.WayfrontTokenCredential).toBe(
            'wayfront_api_token'
        );
        expect(meta.autoSelectCredential).toBe(true);
    });
});
