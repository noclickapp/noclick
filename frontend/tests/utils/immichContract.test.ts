// UNRUN real native editor/schema registrations; generated schema needs separate root lane.
import { describe, expect, it } from 'vitest';
import schema from '../../app/schemas/nodes/immich.json';
import { NODE_SCHEMAS } from '../../app/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '../../app/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '../../app/utils/credentialLabels';
import { AVAILABLE_NODES } from '../../app/components/workflow/nodes/nodeRegistry';

describe('Immich album metadata', () => {
    it('registers the existing API key, exactly two reads and current UUID album selector', () => {
        expect(NODE_SCHEMAS['automation-immich']).toBe(schema);
        expect(AVAILABLE_NODES.filter(n => n.type === 'automation-immich')).toHaveLength(1);
        expect(CREDENTIAL_TYPE_MAP.ImmichAPIKeyCredential).toBe('immich_api_key');
        expect(humanizeCredentialLabel('ImmichAPIKey')).toBe('Immich API Key');
        const native = schema as any;
        const credential = native.$defs.ImmichAPIKeyCredential;
        expect(credential.required).toEqual(expect.arrayContaining(['instance_origin', 'api_key']));
        expect(credential.properties.api_key['ui:widget']).toBe('password');
        expect(credential['x-credential-url']).toBe('https://docs.immich.app/api/');
        expect(credential['x-oauth-provider']).toBeUndefined();
        const refs = native.properties.config.oneOf ?? native.properties.config.anyOf;
        const definitions = refs.map((r: any) => native.$defs[r.$ref.split('/').pop()]);
        expect(definitions.map((d: any) => d.properties.operation.const).sort()).toEqual(['get_album', 'list_albums']);
        for (const d of definitions) {
            expect(d.properties.operation['x-is-trigger']).toBe(false);
            expect(d.properties.include_names.default).toBe(false);
            for (const field of ['assetId', 'id', 'isOwned', 'isShared', 'name', 'key', 'slug', 'page', 'cursor', 'url', 'method']) expect(d.properties[field]).toBeUndefined();
        }
        expect(native.$defs.GetAlbum.properties.album_id.type).toBe('string');
        expect(native.$defs.GetAlbum.properties.album_id.pattern).toContain('-4');
        expect(native.$defs.GetAlbum.properties.album_id['x-dynamic-options'].field_name).toBe('album_id');
        expect(native.$defs.GetAlbum.properties.album_id['x-resource-type']).toBe('immich_album');
    });
});
