// These fixtures check real native schema discovery and credential naming.
// They do not establish editor persistence, account access or a real playback grant.
import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '../../app/schemas/nodes/vdocipher.json';
import { CREDENTIAL_TYPE_MAP } from '../../app/utils/credentialTypeMap';

describe('VdoCipher native contract', () => {
    it('exposes ten closed actions without file transfer or a raw API escape', () => {
        const defs = schema.$defs as Record<string, any>;
        const actions = schema.properties.config.oneOf.map((choice: any) => defs[choice.$ref.split('/').pop()].properties.operation.const);
        expect(new Set(actions).size).toBe(10);
        expect(actions).toContain('create_playback_authorization');
        expect(actions).toContain('create_upload_policy');
        expect(actions).toContain('delete_video');
        expect(actions).not.toContain('upload_file');
        expect(actions).not.toContain('import_url');
        expect(defs.ListVideos.properties.limit.maximum).toBe(40);
        expect(defs.GetVideo.properties.video_id['x-dynamic-options'].field_name).toBe('video_id');
    });
    it('selects the supplied private API secret and preserves the brand label', () => {
        expect(CREDENTIAL_TYPE_MAP.VdoCipherAPISecretCredential).toBe('vdocipher_api_secret');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
        expect(schema.$defs.VdoCipherAPISecretCredential.title).toBe('VdoCipher API Secret');
        const fields = schema.$defs.VdoCipherAPISecretCredential.properties;
        expect(fields.api_secret['ui:widget']).toBe('password');
        expect(fields).not.toHaveProperty('service_url');
        expect(fields).not.toHaveProperty('refresh_token');
    });
});
