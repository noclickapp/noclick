// Verifies Workvivo's discovered schema and manual credential method.
// Keeps draft confirmation and dependent page lookup covered in the generated form.
import { beforeAll, describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '../../app/schemas/nodes/workvivo.json';
import { NODE_SCHEMAS, loadNodeSchemas } from '../../app/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '../../app/utils/credentialTypeMap';

describe('Workvivo native integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-workvivo']));
    it('discovers its schema and static API key credential', () => {
        expect(NODE_SCHEMAS['automation-workvivo']).toBe(schema);
        expect(CREDENTIAL_TYPE_MAP.WorkvivoAPIKeyCredential).toBe('workvivo_api_key');
        const method = methodFromRequirement(requirementsFromSchema(schema)[0]);
        expect(method.method_kind).toBe('api_key');
        const credential = schema.$defs.WorkvivoAPIKeyCredential;
        expect(credential.title).toBe('Workvivo API Key');
        expect(credential.required).toEqual(expect.arrayContaining(['api_base', 'workvivo_id', 'api_key']));
        expect(credential.properties.api_key['ui:widget']).toBe('password');
    });
    it('requires explicit draft confirmation and keeps dependent page lookup', () => {
        expect(schema.$defs.CreateDraftPage.required).toContain('confirm_draft_change');
        expect(schema.$defs.UpdateDraftPage.required).toContain('confirm_draft_change');
        expect(schema.$defs.DeleteDraftPage.required).toContain('confirm_draft_change');
        expect(schema.$defs.FindPage.properties.page_id['x-dynamic-options'].depends_on).toBe('page_scope');
        expect(schema.$defs.ListPages.properties.page_size.maximum).toBe(100);
    });
});
