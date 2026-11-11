// UNRUN actual generated schema/editor registration fixtures for Linkwarden.
// They verify the supplied-token form and three closed reads, without provider calls.
import { describe, expect, it } from 'vitest';
import schema from '../../app/schemas/nodes/linkwarden.json';
import { NODE_SCHEMAS, loadNodeSchemas } from '../../app/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '../../app/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '../../app/utils/credentialLabels';
import { NODE_DEFINITION_FILES } from '../../app/components/workflow/nodes/nodeDefinitions';

describe('Linkwarden scoped metadata', () => {
    it('registers the existing Bearer credential and three closed reads', async () => {
        await loadNodeSchemas(['automation-linkwarden']);
        expect(NODE_SCHEMAS['automation-linkwarden']).toBe(schema);
        expect(NODE_DEFINITION_FILES.filter(([type]) => type === 'automation-linkwarden')).toEqual([['automation-linkwarden', 'integrations/linkwarden']]);
        expect(CREDENTIAL_TYPE_MAP.LinkwardenAccessTokenCredential).toBe('linkwarden_access_token');
        expect(humanizeCredentialLabel('LinkwardenAccessToken')).toBe('Linkwarden Access Token');
        const native = schema as any;
        const credential = native.$defs.LinkwardenAccessTokenCredential;
        expect(credential.required).toEqual(expect.arrayContaining(['instance_origin', 'access_token']));
        expect(credential.properties.access_token['ui:widget']).toBe('password');
        expect(credential['x-oauth-provider']).toBeUndefined();
        expect(credential['x-credential-type']).toBe('linkwarden_access_token');
        const refs = native.properties.config.oneOf ?? native.properties.config.anyOf;
        const definitions = refs.map((r: any) => native.$defs[r.$ref.split('/').pop()]);
        expect(definitions.map((d: any) => d.properties.operation.const).sort()).toEqual(['get_collection', 'list_collections', 'list_tags']);
        for (const d of definitions) {
            expect(d.properties.operation['x-is-trigger']).toBe(false);
            expect(d.properties.include_names.default).toBe(false);
            for (const name of ['url', 'method', 'headers', 'body', 'query', 'cursor', 'limit', 'link_id', 'parent_id', 'user_id', 'create', 'delete']) {
                expect(d.properties[name]).toBeUndefined();
            }
        }
        expect(native.$defs.GetCollection.properties.collection_id['x-dynamic-options'].field_name).toBe('collection_id');
        expect(native.$defs.GetCollection.properties.collection_id.type).toBe('integer');
    });
});
