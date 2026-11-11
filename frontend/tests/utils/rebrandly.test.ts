// UNRUN actual generated-schema/editor registration fixtures; no provider calls.
import { describe, expect, it } from 'vitest';
import schema from '../../app/schemas/nodes/rebrandly.json';
import { NODE_SCHEMAS, loadNodeSchemas, getNodeCredentialInfo } from '../../app/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '../../app/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '../../app/utils/credentialLabels';
import { NODE_DEFINITION_FILES } from '../../app/components/workflow/nodes/nodeDefinitions';

describe('Rebrandly explicit workspace metadata', () => {
    it('registers the manual header credential and five closed reads', async () => {
        await loadNodeSchemas(['automation-rebrandly']);
        expect(NODE_SCHEMAS['automation-rebrandly']).toBe(schema);
        expect(NODE_DEFINITION_FILES.filter(([type]) => type === 'automation-rebrandly')).toEqual([
            ['automation-rebrandly', 'integrations/rebrandly'],
        ]);
        expect(CREDENTIAL_TYPE_MAP.RebrandlyAPIKeyCredential).toBe('rebrandly_api_key');
        expect(getNodeCredentialInfo('automation-rebrandly')?.acceptedTypes).toEqual(['rebrandly_api_key']);
        expect(humanizeCredentialLabel('RebrandlyAPIKey')).toBe('Rebrandly API Key');
        const native = schema as any;
        const credential = native.$defs.RebrandlyAPIKeyCredential;
        expect(credential.properties.api_key['ui:widget']).toBe('password');
        expect(credential.required).toContain('workspace_id');
        expect(credential.properties.workspace_id.minLength).toBe(1);
        expect(credential['x-oauth-provider']).toBeUndefined();
        const refs = native.properties.config.oneOf ?? native.properties.config.anyOf;
        const definitions = refs.map((ref: any) => native.$defs[ref.$ref.split('/').pop()]);
        expect(definitions.map((d: any) => d.properties.operation.const).sort()).toEqual([
            'get_domain', 'get_link', 'list_domains', 'list_links', 'list_workspaces',
        ]);
        for (const definition of definitions) {
            expect(definition.properties.operation['x-is-trigger']).toBe(false);
            expect(definition.properties.include_names.default).toBe(false);
            for (const name of ['url', 'method', 'headers', 'body', 'query', 'destination', 'shortUrl', 'owner', 'publish', 'create', 'delete']) {
                expect(definition.properties[name]).toBeUndefined();
            }
            if (definition.properties.domain_id) {
                expect(definition.properties.domain_id['x-dynamic-options'].depends_on).toEqual(['workspace_id']);
            }
            if (definition.properties.link_id) {
                expect(definition.properties.link_id['x-dynamic-options'].depends_on).toEqual(['workspace_id', 'domain_id']);
            }
            if (definition.properties.limit) {
                expect(definition.properties.limit.maximum).toBe(25);
                expect(definition.properties.limit.minimum).toBe(1);
                expect(definition.properties.limit.default).toBe(25);
            }
        }
    });
});
