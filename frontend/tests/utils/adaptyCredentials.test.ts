// Adapty schema contracts keep the app-scoped connection and profile forms aligned.
// Saved connection selection is checked against staging’s canvas credential helper.
import { describe, expect, it } from 'vitest';
import { NODE_SCHEMAS, filterConfigForExecution, isTriggerSource, loadNodeSchemas } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';

await loadNodeSchemas(['automation-adapty']);

describe('Adapty app-scoped connection and profile forms', () => {
    it('selects a saved app connection when adding an Adapty node', () => {
        upsertCredentialsIntoCache([{ id: 'adapty-test-credential', name: 'Adapty test', credential_type: 'adapty_api_key', owned_by_me: true }]);
        expect(autoSelectCredentialFromCache('automation-adapty')).toEqual({ adapty_api_key: 'adapty-test-credential' });
    });
    it('requires an app secret and known profile without inventing OAuth or account identity', () => {
        const schema = NODE_SCHEMAS['automation-adapty'];
        const key = schema.$defs.AdaptyAPIKeyCredential;
        expect(CREDENTIAL_TYPE_MAP[key.title]).toBe('adapty_api_key');
        expect(humanizeCredentialLabel(key.title)).toBe('Adapty API Key Credential');
        expect(key.required).toEqual(['secret_key', 'app_id', 'verification_profile_id']);
        expect(key.properties.secret_key['ui:widget']).toBe('password');
        expect(key.properties.app_id.format).toBe('uuid');
        expect(key['x-oauth-provider']).toBeUndefined();
        expect(schema['x-agent-tool-provider']).toBe(true);
    });
    it('keeps access selectors dependent on the selected identifier and kind', () => {
        const fields = NODE_SCHEMAS['automation-adapty'].$defs.AdaptyGrantAccessLevelConfig.properties;
        expect(fields.access_level_id['x-dynamic-options'].depends_on).toEqual(['identifier_kind', 'profile_identifier']);
        expect(fields.profile_identifier['x-dynamic-options'].depends_on).toBe('identifier_kind');
        expect(fields.expires_at.description).toContain('lifetime');
        expect(isTriggerSource('automation-adapty', 'get_profile')).toBe(false);
    });
    it('preserves explicit null revocation and drops stale profile-write fields', () => {
        expect(filterConfigForExecution('automation-adapty', {operation: 'revoke_access_level',
            identifier_kind: 'profile_id', profile_identifier: 'fixture', access_level_id: 'premium',
            revoke_at: null, installation_meta: {device_id: 'stale'}, first_name: 'stale', expires_at: 'stale'}))
            .toEqual({operation: 'revoke_access_level', identifier_kind: 'profile_id',
                profile_identifier: 'fixture', access_level_id: 'premium', revoke_at: null});
        expect(NODE_SCHEMAS['automation-adapty'].$defs.AdaptyCreateProfileConfig.required).toContain('installation_meta');
    });
});
