// UNRUN actual generated schema/editor registration fixtures for Linkwarden.
// They verify the supplied-token form and three closed reads, without provider calls.
import { describe, expect, it } from 'vitest';
import schema from '../../app/schemas/nodes/linkwarden.json';
import { NODE_SCHEMAS } from '../../app/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '../../app/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '../../app/utils/credentialLabels';
import { AVAILABLE_NODES } from '../../app/components/workflow/nodes/nodeRegistry';

describe('Linkwarden scoped metadata', () => {
    it('registers the existing Bearer credential and three closed reads', () => {
        expect(NODE_SCHEMAS['automation-linkwarden']).toBe(schema);
        expect(AVAILABLE_NODES.filter(n => n.type === 'automation-linkwarden')).toHaveLength(1);
        expect(CREDENTIAL_TYPE_MAP.LinkwardenAccessTokenCredential).toBe('linkwarden_access_token');
        expect(humanizeCredentialLabel('LinkwardenAccessToken')).toBe('Linkwarden Access Token');
        const native = schema as any;
        const credential = native.$defs.LinkwardenAccessTokenCredential;
        expect(credential.required).toEqual(expect.arrayContaining(['instance_origin', 'access_token']));
        expect(credential.properties.access_token['ui:widget']).toBe('password');
        expect(credential['x-oauth-provider']).toBeUndefined();
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
