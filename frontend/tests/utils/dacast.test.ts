import { describe, expect, it } from 'vitest';
import schema from '../../app/schemas/nodes/dacast.json';
import meta from '../../app/schemas/nodeMeta/dacast.json';
import { DacastNode } from '~/components/workflow/nodes/integrations/dacast';
import { getNodeMetadata } from '~/components/workflow/nodes/nodeRegistry';

describe('Dacast integration', () => {
    it('discovers the media integration and its folder trigger', () => {
        expect(getNodeMetadata('automation-dacast')?.label).toBe(DacastNode.label);
        expect(DacastNode.category).toBe('media');
        expect(meta.nodeMeta.triggerOperations).toEqual(['on_new_folder']);
        expect(schema.$defs.OnNewFolder.properties.operation['x-is-trigger']).toBe(true);
    });

    it('offers a manual API key and explicit resource restrictions', () => {
        const credential = schema.$defs.DacastAPIKeyCredential;
        expect(credential.title).toBe('Dacast API Key');
        expect(credential.properties.credential_type.default).toBe('dacast_api_key');
        expect(credential.properties.api_key['ui:widget']).toBe('password');
        expect(credential.required).toEqual(['api_key']);
        expect(credential.properties.include_labels.default).toBe(false);
        expect(credential.properties.monitor_all_folders.default).toBe(false);
        expect(JSON.parse(credential.properties.approved_resources_json.default)).toEqual({
            channels: [], videos: [], folders: [], playlists: [],
        });
    });

    it('uses the documented folder page limit', () => {
        expect(schema.$defs.ListFolders.properties.per_page.maximum).toBe(50);
        expect(schema.$defs.ListVideos.properties.per_page.maximum).toBe(100);
    });
});
