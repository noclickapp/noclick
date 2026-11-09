import { describe, expect, it } from 'vitest';
import schema from '~/schemas/nodes/followupboss.json';
import metadata from '~/schemas/nodeMeta/followupboss.json';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { FollowUpBossNode } from '~/components/workflow/nodes/integrations/followupboss';

describe('Follow Up Boss self-registering definition', () => {
    it('publishes CRM metadata and the signed people-event trigger', () => {
        expect(FollowUpBossNode.type).toBe('automation-followupboss');
        expect(FollowUpBossNode.category).toBe('crm-sales');
        expect(metadata.nodeMeta.triggerOperations).toEqual(['on_people_event']);
        expect(Object.keys(schema.properties.config.discriminator.mapping)).toHaveLength(18);
    });
    it('exposes hand-connectable key and supplied-token credentials', () => {
        const key = schema.$defs.FollowUpBossAPIKeyCredential;
        const token = schema.$defs.FollowUpBossBearerTokenCredential;
        expect(key.properties.credential_type.default).toBe('followupboss_api_key');
        expect(token.properties.credential_type.default).toBe('followupboss_bearer_token');
        expect(key.properties.system_key['ui:widget']).toBe('password');
        expect(key.properties.api_key['ui:widget']).toBe('password');
        expect(token.required).toContain('expires_at');
        expect(token['x-credential-type']).toBe('api_key');
        expect(humanizeCredentialLabel(key.title)).toBe('Follow Up Boss API Key');
    });
    it('requires registered system identification for both credential methods', () => {
        for (const credential of [schema.$defs.FollowUpBossAPIKeyCredential, schema.$defs.FollowUpBossBearerTokenCredential]) {
            expect(credential.required).toContain('system');
            expect(credential.required).toContain('system_key');
            expect(credential.required).not.toContain('credential_type');
        }
    });
});
