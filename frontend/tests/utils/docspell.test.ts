// Generated schema and editor registration contracts for Docspell.
import { describe, expect, it } from 'vitest';
import { kindFromCredentialType } from '../../app/lib/credentialMethodKind';
import schema from '../../app/schemas/nodes/docspell.json';
import { NODE_SCHEMAS, loadNodeSchemas } from '../../app/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '../../app/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '../../app/utils/credentialLabels';
import { NODE_DEFINITION_FILES } from '../../app/components/workflow/nodes/nodeDefinitions';

describe('Docspell metadata contracts', () => {
    it('registers the user-token form and exactly three closed reads', async () => {
        await loadNodeSchemas(['automation-docspell']);
        expect(NODE_SCHEMAS['automation-docspell']).toBe(schema);
        expect(NODE_DEFINITION_FILES.filter(([type]) => type === 'automation-docspell')).toEqual([['automation-docspell', 'integrations/docspell']]);
        expect(CREDENTIAL_TYPE_MAP.DocspellAuthTokenCredential).toBe('docspell_auth_token');
        expect(humanizeCredentialLabel('DocspellAuthToken')).toBe('Docspell Auth Token');
        const native = schema as any;
        const credential = native.$defs.DocspellAuthTokenCredential;
        expect(credential.required).toEqual(expect.arrayContaining(['instance_origin', 'auth_token']));
        expect(credential.properties.auth_token['ui:widget']).toBe('password');
        expect(credential['x-oauth-provider']).toBeUndefined();
        expect(kindFromCredentialType(credential['x-credential-type'])).toBe('api_key');
        const refs = native.properties.config.oneOf ?? native.properties.config.anyOf;
        const definitions = refs.map((r: any) => native.$defs[r.$ref.split('/').pop()]);
        expect(definitions.map((d: any) => d.properties.operation.const).sort()).toEqual(['get_folder', 'list_folders', 'list_tags']);
        for (const d of definitions) {
            expect(d.properties.operation['x-is-trigger']).toBe(false);
            expect(d.properties.include_names.default).toBe(false);
            for (const field of ['q', 'sort', 'owning', 'full', 'page', 'cursor', 'url', 'method', 'tag_id', 'admin_secret', 'share_token']) expect(d.properties[field]).toBeUndefined();
        }
        expect(native.$defs.GetFolder.properties.folder_id.type).toBe('string');
        expect(native.$defs.GetFolder.properties.folder_id['x-dynamic-options'].field_name).toBe('folder_id');
    });
});
