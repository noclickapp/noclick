import { beforeAll, describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '../../app/schemas/nodes/telnyx.json';
import { NODE_SCHEMAS, loadNodeSchemas } from '../../app/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '../../app/utils/credentialTypeMap';

describe('Telnyx integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-telnyx']));
    it('discovers a paste-in API key method', () => {
        expect(NODE_SCHEMAS['automation-telnyx']).toBe(schema);
        expect(CREDENTIAL_TYPE_MAP.TelnyxAPIKeyCredential).toBe('telnyx_api_key');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
        expect(schema.$defs.TelnyxAPIKeyCredential.title).toBe('Telnyx API Key');
        expect(schema.$defs.TelnyxAPIKeyCredential.properties.api_key['ui:widget']).toBe('password');
    });
});
