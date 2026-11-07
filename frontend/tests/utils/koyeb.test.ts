// Koyeb's native form contracts keep credentials and selected resource parents explicit.
// These prepared regressions cover generated schema consumers; execution is ungranted.
import { beforeAll, describe, expect, it } from 'vitest';
import { NODE_SCHEMAS, loadNodeSchemas, filterConfigForExecution, isTriggerSource, isAgentToolProviderType } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

describe('Koyeb organization-bound inventory forms', () => {
    beforeAll(() => loadNodeSchemas(['automation-koyeb']));
    it('uses a manual token with an explicit organization and no OAuth claim', () => {
        const schema = NODE_SCHEMAS['automation-koyeb'];
        const key = schema.$defs.KoyebAPIKeyCredential;
        expect(CREDENTIAL_TYPE_MAP[key.title]).toBe('koyeb_api_key');
        expect(humanizeCredentialLabel(key.title)).toBe('Koyeb API Token');
        expect(key.required).toEqual(['api_key', 'organization_id']);
        expect(key.properties.api_key['ui:widget']).toBe('password');
        expect(key['x-oauth-provider']).toBeUndefined();
        expect(isAgentToolProviderType('automation-koyeb')).toBe(true);
    });
    it('declares the actual app and service selector ancestry', () => {
        const defs = NODE_SCHEMAS['automation-koyeb'].$defs;
        const props = defs.KoyebGetDeploymentConfig.properties;
        expect(props.app_id['x-resource-type']).toBe('koyeb_app');
        expect(props.service_id['x-dynamic-options'].depends_on).toBe('app_id');
        expect(props.deployment_id['x-dynamic-options'].depends_on).toBe('service_id');
        expect(defs.KoyebListInstancesConfig.properties.limit.maximum).toBe(100);
        expect(defs.KoyebDeleteEmptyAppConfig.required).toContain('expected_name');
        expect(isTriggerSource('automation-koyeb', 'list_instances')).toBe(false);
    });
    it('drops stale write and child fields when switching to an app read', () => {
        expect(filterConfigForExecution('automation-koyeb', {operation: 'get_app', app_id: 'fixture',
            service_id: 'stale', name: 'stale', expected_name: 'stale', page_token: 'stale'}))
            .toEqual({operation: 'get_app', app_id: 'fixture'});
        expect(NODE_SCHEMAS['automation-koyeb'].$defs.KoyebCreateEmptyAppConfig.properties.name.description)
            .toContain('managed subdomain');
    });
});
