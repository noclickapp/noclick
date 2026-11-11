// Skyvia schema, palette and credential contract against staging's lazy loaders.
import { beforeAll, describe, expect, it } from 'vitest';
import schema from '../../app/schemas/nodes/skyvia.json';
import { NODE_SCHEMAS, loadNodeSchemas } from '../../app/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '../../app/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '../../app/utils/credentialLabels';
import { NODE_DEFINITION_FILES } from '../../app/components/workflow/nodes/nodeDefinitions';

describe('Skyvia native contract', () => {
    beforeAll(async () => { await loadNodeSchemas(['automation-skyvia']); });
    it('registers one editor node/schema and the actual supplied token method', () => {
        expect(NODE_SCHEMAS['automation-skyvia']).toBe(schema);
        expect(NODE_DEFINITION_FILES.filter(([type]) => type === 'automation-skyvia')).toEqual([['automation-skyvia', 'integrations/skyvia']]);
        expect(CREDENTIAL_TYPE_MAP.SkyviaAPITokenCredential).toBe('skyvia_api_token');
        expect(humanizeCredentialLabel('SkyviaAPIToken')).toBe('Skyvia API Token');
        const credential = (schema as any).$defs.SkyviaAPITokenCredential;
        expect(credential.properties.api_token['ui:widget']).toBe('password');
        expect(credential['x-oauth-provider']).toBeUndefined();
        expect(credential['x-oauth-scopes']).toBeUndefined();
        expect(credential.properties.workspace_ids.minItems).toBe(1);
        expect(credential.properties.workspace_ids.maxItems).toBe(50);
    });
    it('keeps ten typed read actions, bounded documented paging and dependent IDs', () => {
        const native = schema as any;
        const refs = native.properties.config.oneOf ?? native.properties.config.anyOf;
        const definitions = refs.map((ref: any) => native.$defs[ref.$ref.split('/').pop()]);
        expect(definitions.map((definition: any) => definition.properties.operation.const).sort()).toEqual([
            'get_automation', 'get_backup', 'get_connection', 'get_integration', 'get_workspace',
            'list_automations', 'list_backups', 'list_connections', 'list_integrations', 'list_workspaces',
        ]);
        for (const definition of definitions) {
            expect(definition.properties.operation['x-is-trigger']).toBe(false);
            expect(definition.properties.include_names.default).toBe(false);
            for (const field of ['connection_id', 'integration_id', 'backup_id', 'automation_id']) {
                if (definition.properties[field]) expect(definition.properties[field]['x-dynamic-options'].depends_on).toEqual(['workspace_id']);
            }
            if (definition.properties.take) {
                expect(definition.properties.take.maximum).toBe(100);
                expect(definition.properties.skip.maximum).toBe(10000);
            }
            for (const field of ['url', 'method', 'body', 'query', 'sql', 'settings']) expect(definition.properties[field]).toBeUndefined();
        }
    });
});
