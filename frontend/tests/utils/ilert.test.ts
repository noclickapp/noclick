// ilert's native credential and resource schema use the current frontend consumers.
// These source fixtures await native generation and a separate frontend test grant.
import { describe, expect, it } from 'vitest';
import { NODE_SCHEMAS, filterConfigForExecution, isTriggerSource, loadNodeSchemas } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

await loadNodeSchemas(['automation-ilert']);

describe('ilert user REST key metadata', () => {
    it('requires the existing key and verified actor with explicit optional team context', () => {
        const schema = NODE_SCHEMAS['automation-ilert'];
        const cred = schema.$defs.IlertAPIKeyCredential;
        expect(cred.required).toEqual(['access_token', 'actor_id']);
        expect(cred.properties.access_token['ui:widget']).toBe('password');
        expect(cred.properties.access_token.maxLength).toBe(8192);
        expect(cred.properties.team_context.anyOf.some((s: { minimum?: number }) => s.minimum === -1)).toBe(true);
        expect(CREDENTIAL_TYPE_MAP[cred.title]).toBe('ilert_api_key');
        expect(humanizeCredentialLabel(cred.title)).toBe('Ilert API Key Credential');
        expect(cred['x-oauth-provider']).toBeUndefined();
        expect(schema['x-agent-tool-provider']).toBe(true);
    });
    it('retains full team/service ancestry with per-route numeric caps', () => {
        const defs = NODE_SCHEMAS['automation-ilert'].$defs;
        expect(defs.IlertGetIncidentConfig.required).toEqual(['team_id', 'service_id', 'incident_id']);
        expect(defs.IlertGetIncidentConfig.properties.service_id['x-dynamic-options'].depends_on).toBe('team_id');
        expect(defs.IlertGetIncidentConfig.properties.incident_id['x-dynamic-options'].depends_on).toBe('service_id');
        expect(defs.IlertTeamsConfig.properties.limit.maximum).toBe(100);
        expect(defs.IlertStatusPagesConfig.properties.limit.maximum).toBe(50);
        expect(defs.IlertTeamsConfig.properties.include_names.default).toBe(false);
        expect(isTriggerSource('automation-ilert', 'list_incidents')).toBe(false);
    });
    it('filters stale page fields while preserving selected incident ancestry', () => {
        expect(filterConfigForExecution('automation-ilert', { operation: 'get_incident', team_id: '1',
            service_id: '7', incident_id: '9', include_names: false, limit: 100, offset: 50, page_token: 'old' }))
            .toEqual({ operation: 'get_incident', team_id: '1', service_id: '7', incident_id: '9', include_names: false });
    });
});
