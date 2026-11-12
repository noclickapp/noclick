// Native registration and credential/schema contract fixtures.
// They exercise current maps and generated metadata without provider calls.
import { describe, expect, it } from 'vitest';
import schema from '../../app/schemas/nodes/bytescale.json';
import { NODE_SCHEMAS, loadNodeSchemas } from '../../app/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '../../app/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '../../app/utils/credentialLabels';
import { NODE_DEFINITION_FILES } from '../../app/components/workflow/nodes/nodeDefinitions';

describe('Bytescale native management metadata', () => {
    it('registers the secret management family and one native editor node', async () => {
        await loadNodeSchemas(['automation-bytescale']);
        expect(NODE_SCHEMAS['automation-bytescale']).toBe(schema);
        expect(NODE_DEFINITION_FILES.filter(([type]) => type === 'automation-bytescale')).toEqual([['automation-bytescale', 'integrations/bytescale']]);
        expect(CREDENTIAL_TYPE_MAP.BytescaleSecretAPIKeyCredential).toBe('bytescale_secret_api_key');
        expect(humanizeCredentialLabel('BytescaleSecretAPIKey')).toBe('Bytescale Secret API Key');
        const native = schema as any;
        const credential = native.$defs.BytescaleSecretAPIKeyCredential;
        expect(credential.properties.api_key['ui:widget']).toBe('password');
        expect(credential.properties.account_id.pattern).toBe('^[A-Za-z0-9]{7}$');
        expect(credential.properties.folder_paths.maxItems).toBe(20);
        expect(credential['x-oauth-provider']).toBeUndefined();
        expect(credential['x-credential-type']).toBe('bytescale_secret_api_key');
        const refs = native.properties.config.oneOf ?? native.properties.config.anyOf;
        const definitions = refs.map((ref: any) => native.$defs[ref.$ref.split('/').pop()]);
        expect(definitions.map((d: any) => d.properties.operation.const).sort()).toEqual([
            'get_file_details', 'get_folder_details', 'list_folder',
        ]);
        for (const definition of definitions) {
            expect(definition.properties.operation['x-is-trigger']).toBe(false);
            expect(definition.properties.include_paths_and_names.default).toBe(false);
            for (const name of ['url', 'method', 'body', 'query', 'permissions', 'upload', 'delete']) {
                expect(definition.properties[name]).toBeUndefined();
            }
            if (definition.properties.file_path) {
                expect(definition.properties.file_path['x-dynamic-options'].depends_on).toEqual(['folder_path']);
            }
            if (definition.properties.limit) expect(definition.properties.limit.maximum).toBe(100);
        }
    });
});
