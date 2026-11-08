import { describe, expect, it } from 'vitest';
import { NODE_SCHEMAS, filterConfigForExecution, isTriggerSource, loadNodeSchemas } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

await loadNodeSchemas(['automation-krisp']);

describe('Krisp native scoped personal key', () => {
    it('renders the exact key family and actual optional expiry without an OAuth callback', () => {
        const schema = NODE_SCHEMAS['automation-krisp'];
        const key = schema.$defs.KrispAPIKeyCredential;
        expect(key.required).toEqual(['api_key']);
        expect(key.properties.api_key.minLength).toBe(103);
        expect(key.properties.api_key.maxLength).toBe(103);
        expect(key.properties.api_key['ui:widget']).toBe('password');
        expect(key.properties.scopes.items.enum).toEqual(['read', 'write']);
        expect(key.properties.expires_at.anyOf.some((p: { type?: string }) => p.type === 'null')).toBe(true);
        expect(key['x-oauth-provider']).toBeUndefined();
        expect(CREDENTIAL_TYPE_MAP[key.title]).toBe('krisp_api_key');
        expect(humanizeCredentialLabel(key.title)).toBe('Krisp API Key');
        expect(schema['x-agent-tool-provider']).toBe(true);
    });

    it('keeps meeting selection and explicit transcript privacy choice', () => {
        const fields = NODE_SCHEMAS['automation-krisp'].$defs.KrispGetTranscriptConfig.properties;
        expect(fields.meeting_id['x-resource-type']).toBe('krisp_meeting');
        expect(fields.meeting_id['x-dynamic-options'].field_name).toBe('meeting_id');
        expect(fields.include_speaker_names.default).toBe(false);
        expect(isTriggerSource('automation-krisp', 'list_meetings')).toBe(false);
    });

    it('preserves false status filters and strips stale fields from other operations', () => {
        expect(filterConfigForExecution('automation-krisp', {
            operation: 'list_meeting_action_items', meeting_id: 'meeting_fixture', completed: false,
            limit: 20, include_assignee: false, query: 'stale', include_speaker_names: true,
        })).toEqual({ operation: 'list_meeting_action_items', meeting_id: 'meeting_fixture',
            completed: false, limit: 20, include_assignee: false });
    });
});
