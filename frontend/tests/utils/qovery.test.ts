// Native schema, credential and resource-parent contracts.
// Generated artifacts are required; these do not prove provider access or UI persistence.
import { describe, expect, it } from 'vitest';
import schema from '../../app/schemas/nodes/qovery.json';
import { CREDENTIAL_TYPE_MAP } from '../../app/utils/credentialTypeMap';
import { humanizeCredentialLabel, fixWordCasing } from '../../app/utils/credentialLabels';

describe('Qovery native contract', () => {
    it('exposes exactly 17 metadata actions, with parent-bound selectors', () => {
        const defs = schema.$defs as Record<string, any>;
        const actions = schema.properties.config.oneOf.map((choice: any) => defs[choice.$ref.split('/').pop()].properties.operation.const);
        expect(new Set(actions)).toEqual(new Set([
            'get_organization', 'list_projects', 'get_project', 'create_empty_project', 'update_empty_project',
            'list_environments', 'get_environment', 'create_empty_environment', 'rename_empty_environment',
            'get_environment_status', 'list_clusters', 'get_cluster', 'get_cluster_status', 'list_services',
            'get_service_status', 'list_environment_deployments', 'list_service_deployments',
        ]));
        expect(defs.GetEnvironment.properties.environment_id['x-dynamic-options'].depends_on).toBe('project_id');
        expect(defs.ServiceStatus.properties.service_id['x-dynamic-options'].depends_on).toBe('environment_id');
        expect(defs.UpdateProject.properties.expected_snapshot.pattern).toBe('^[0-9a-f]{64}$');
        expect(defs.CreateEnvironment.properties.mode.enum).toEqual(['DEVELOPMENT', 'PRODUCTION', 'STAGING']);
    });
    it('selects only supplied machine tokens and keeps their bytes private', () => {
        expect(CREDENTIAL_TYPE_MAP.QoveryAPITokenCredential).toBe('qovery_api_token');
        expect(humanizeCredentialLabel(schema.$defs.QoveryAPITokenCredential.title)).toBe('Qovery API Token');
        expect(fixWordCasing(schema.$defs.QoveryAPITokenCredential.title)).toBe('Qovery API Token');
        const fields = schema.$defs.QoveryAPITokenCredential.properties;
        expect(fields.api_token['ui:widget']).toBe('password');
        expect(fields.organization_id.pattern).toContain('[0-9a-f]');
        expect(fields).not.toHaveProperty('access_token');
        expect(fields).not.toHaveProperty('refresh_token');
        expect(schema.$defs.QoveryAPITokenCredential).not.toHaveProperty('x-oauth-provider');
    });
});
