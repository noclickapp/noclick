// Brightcove's real generated credential and operation surfaces remain aligned.
import { beforeAll, describe, expect, it } from 'vitest';
import { NODE_SCHEMAS, loadNodeSchemas, filterConfigForExecution, isTriggerSource } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

describe('Brightcove native credential and catalog controls', () => {
    beforeAll(() => loadNodeSchemas(['automation-brightcove']));
    it('uses a manual client form with hidden finite token fields', () => {
        const schema = NODE_SCHEMAS['automation-brightcove'];
        const credential = schema.$defs.BrightcoveClientCredential;
        expect(CREDENTIAL_TYPE_MAP[credential.title]).toBe('brightcove_client_credentials');
        expect(humanizeCredentialLabel(credential.title)).toBe('Brightcove API Client');
        expect(credential.required).toEqual(expect.arrayContaining(['account_id', 'client_id', 'client_secret']));
        expect(credential['x-oauth-provider']).toBeUndefined();
        expect(credential.properties.client_secret['ui:widget']).toBe('password');
        expect(credential.properties.access_token['ui:hidden']).toBe(true);
        expect(credential.properties.expires_at['ui:hidden']).toBe(true);
        expect(schema['x-agent-tool-provider']).toBe(true);
    });

    it('keeps only draft metadata and declared parent membership configuration', () => {
        expect(filterConfigForExecution('automation-brightcove', {
            operation: 'create_video_draft', name: 'Fixture', custom_fields: { topic: null },
            folder_id: 'stale',
        })).toEqual({ operation: 'create_video_draft', name: 'Fixture', custom_fields: { topic: null } });
        const schema = NODE_SCHEMAS['automation-brightcove'];
        const draft = schema.$defs.BrightcoveCreateVideoConfig;
        expect(draft.additionalProperties).toBe(false);
        expect(draft.properties).not.toHaveProperty('state');
        expect(draft.properties).not.toHaveProperty('sources');
        const video = schema.$defs.BrightcoveRemoveFolderVideoConfig.properties.video_id;
        expect(video['x-dynamic-options'].depends_on).toBe('folder_id');
        expect(video['x-resource-type']).toBe('brightcove_video');
        expect(isTriggerSource('automation-brightcove', 'list_videos')).toBe(false);
    });

    it('preserves intentional false and empty playlist replacement', () => {
        expect(filterConfigForExecution('automation-brightcove', {
            operation: 'update_playlist', playlist_id: '789', favorite: false, video_ids: [],
            video_id: '456',
        })).toEqual({ operation: 'update_playlist', playlist_id: '789', favorite: false, video_ids: [] });
    });
});
