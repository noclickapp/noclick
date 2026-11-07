// Native native schema/editor registration fixtures.
import { describe, expect, it } from 'vitest';
import schema from '../../app/schemas/nodes/audiobookshelf.json';
import { NODE_SCHEMAS, loadNodeSchemas } from '../../app/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '../../app/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '../../app/utils/credentialLabels';
import { NODE_DEFINITION_FILES } from '../../app/components/workflow/nodes/nodeDefinitions';
import { kindFromCredentialType } from '../../app/lib/credentialMethodKind';

describe('Audiobookshelf library and author metadata', () => {
    it('registers the server API key form, four reads and dependent author selector', async () => {
        await loadNodeSchemas(['automation-audiobookshelf']);
        expect(NODE_SCHEMAS['automation-audiobookshelf']).toBe(schema);
        expect(NODE_DEFINITION_FILES.filter(([type]) => type === 'automation-audiobookshelf')).toHaveLength(1);
        expect(CREDENTIAL_TYPE_MAP.AudiobookshelfAPIKeyCredential).toBe('audiobookshelf_api_key');
        expect(humanizeCredentialLabel('AudiobookshelfAPIKey')).toBe('Audiobookshelf API Key');
        const native = schema as any;
        const credential = native.$defs.AudiobookshelfAPIKeyCredential;
        expect(credential.required).toEqual(expect.arrayContaining(['instance_origin', 'api_key']));
        expect(credential.properties.api_key['ui:widget']).toBe('password');
        expect(credential['x-oauth-provider']).toBeUndefined();
        expect(kindFromCredentialType(credential['x-credential-type'])).toBe('api_key');
        const refs = native.properties.config.oneOf ?? native.properties.config.anyOf;
        const definitions = refs.map((r: any) => native.$defs[r.$ref.split('/').pop()]);
        expect(definitions.map((d: any) => d.properties.operation.const).sort()).toEqual(['get_author', 'get_library', 'list_libraries', 'list_library_authors']);
        for (const d of definitions) {
            expect(d.properties.operation['x-is-trigger']).toBe(false);
            expect(d.properties.include_names.default).toBe(false);
            for (const field of ['include', 'minified', 'page', 'cursor', 'url', 'method', 'filter', 'sort', 'token', 'user_id']) expect(d.properties[field]).toBeUndefined();
        }
        expect(native.$defs.GetAuthor.properties.library_id.type).toBe('string');
        expect(native.$defs.GetAuthor.properties.author_id['x-dynamic-options'].depends_on).toBe('library_id');
        expect(native.$defs.GetAuthor.properties.author_id['x-resource-type']).toBe('audiobookshelf_author');
    });
});
