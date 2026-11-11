// Prepared actual frontend schema-consumer cases; runtime remains ungranted.
import { beforeAll, describe, expect, it } from 'vitest';
import { NODE_SCHEMAS, loadNodeSchemas, filterConfigForExecution, isTriggerSource } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

describe('Xata current issued OAuth metadata', () => {
    beforeAll(() => loadNodeSchemas(['automation-xata']));
    it('requires the existing token and grant metadata without a fictitious connect popup', () => {
        const schema = NODE_SCHEMAS['automation-xata'];
        const cred = schema.$defs.XataIssuedOAuthCredential;
        expect(cred.required).toEqual(['access_token', 'granted_scopes']);
        expect(cred.properties.access_token['ui:widget']).toBe('password');
        expect(CREDENTIAL_TYPE_MAP[cred.title]).toBe('xata_issued_oauth');
        expect(humanizeCredentialLabel(cred.title)).toBe('Xata Issued OAuth Credential');
        expect(cred['x-oauth-provider']).toBeUndefined();
        expect(cred.properties.actor_id).toBeUndefined();
        expect(schema['x-agent-tool-provider']).toBe(true);
    });
    it('keeps full organization/project/backup dependency scope and local bounds', () => {
        const defs = NODE_SCHEMAS['automation-xata'].$defs;
        expect(defs.XataGetBackupConfig.required).toEqual(['organization_id', 'project_id', 'backup_id']);
        expect(defs.XataGetBackupConfig.properties.project_id['x-dynamic-options'].depends_on).toBe('organization_id');
        expect(defs.XataGetBackupConfig.properties.backup_id['x-dynamic-options'].depends_on).toBe('project_id');
        expect(defs.XataGetBackupConfig.properties.backup_id['x-dynamic-options'].field_name).toBe('backup_id');
        expect(defs.XataGetProjectConfig.properties.page_token).toBeUndefined();
        expect(defs.XataGetProjectConfig.properties.connectionString).toBeUndefined();
        expect(defs.XataBranchesConfig.properties.max_items.maximum).toBe(1000);
        expect(defs.XataBranchesConfig.properties.include_names.default).toBe(false);
        expect(isTriggerSource('automation-xata', 'list_branches')).toBe(false);
    });
    it('filters backup fields when switching to project detail', () => {
        expect(filterConfigForExecution('automation-xata', { operation: 'get_project', organization_id: 'org-a',
            project_id: 'project-a', include_names: false, backup_id: 'backup-a' }))
            .toEqual({ operation: 'get_project', organization_id: 'org-a', project_id: 'project-a', include_names: false });
    });
});
