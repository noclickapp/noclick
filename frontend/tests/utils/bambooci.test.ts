// Exercise Bamboo CI through staging's lazy schema and credential metadata readers.
import { beforeAll, describe, expect, it } from 'vitest';
import { NODE_SCHEMAS, filterConfigForExecution, isTriggerSource, loadNodeSchemas } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

describe('Bamboo CI instance and project-bound PAT', () => {
    beforeAll(async () => {
        await loadNodeSchemas(['automation-bambooci']);
    });
    it('requires independently supplied instance, project and existing PAT without an OAuth popup', () => {
        const schema = NODE_SCHEMAS['automation-bambooci'];
        const cred = schema.$defs.BambooPATCredential;
        expect(cred.required).toEqual(['instance_url', 'project_key', 'access_token']);
        expect(cred.properties.access_token['ui:widget']).toBe('password');
        expect(CREDENTIAL_TYPE_MAP[cred.title]).toBe('bambooci_pat');
        expect(humanizeCredentialLabel(cred.title)).toBe('Bamboo CI Personal Access Token');
        expect(cred['x-oauth-provider']).toBeUndefined();
        expect(cred.properties.actor_id).toBeUndefined();
        expect(schema['x-agent-tool-provider']).toBe(true);
    });
    it('preserves project/plan context and conservative local defaults', () => {
        const defs = NODE_SCHEMAS['automation-bambooci'].$defs;
        expect(defs.BambooCIGetPlanConfig.required).toEqual(['project_key', 'plan_key']);
        expect(defs.BambooCIGetPlanConfig.properties.plan_key['x-dynamic-options'].depends_on).toBe('project_key');
        expect(defs.BambooCIPlansConfig.properties.max_items.maximum).toBe(1000);
        expect(defs.BambooCIPlansConfig.properties.include_names.default).toBe(false);
        expect(isTriggerSource('automation-bambooci', 'list_plans')).toBe(false);
    });
    it('drops stale resource keys when switching to the project catalog', () => {
        expect(filterConfigForExecution('automation-bambooci', { operation: 'list_projects', project_key: 'PROJ',
            plan_key: 'PROJ-PLAN', include_names: false }))
            .toEqual({ operation: 'list_projects', include_names: false });
    });
});
