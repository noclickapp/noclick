// Scalr self-registering schema, credential, agent and icon seams.
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeAll, describe, expect, it } from 'vitest';
import { ScalrNode } from '~/components/workflow/nodes/integrations/scalr';
import { NODE_SCHEMAS, getNodeCredentialInfo, isAgentToolProviderType, loadNodeSchemas } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
const TYPE = 'automation-scalr', FAMILY = 'scalr_token';
beforeAll(() => loadNodeSchemas([TYPE]));
describe('Scalr native metadata', () => {
  it('uses the actual credential definition and exact seven operations', () => {
    expect(getNodeCredentialInfo(TYPE)?.acceptedTypes).toEqual([FAMILY]);
    expect(getNodeCredentialInfo(TYPE)?.label).toBe('Scalr Existing Bearer Token');
    expect(getCredentialTypeFromSchemaTitle('ScalrTokenCredential')).toBe(FAMILY);
    expect(isAgentToolProviderType(TYPE)).toBe(true);
    expect(ScalrNode.type).toBe(TYPE);
    const schema = NODE_SCHEMAS[TYPE], key = schema.$defs.ScalrTokenCredential;
    expect(key.required).toEqual(expect.arrayContaining(['access_token', 'tenant_host', 'account_id']));
    expect(key.properties.access_token['ui:widget']).toBe('password');
    expect(key.properties.refresh_token).toBeUndefined();
    expect(key['x-oauth-provider']).toBeUndefined();
    const ops = schema.properties.config.oneOf.map((r: { $ref: string }) => schema.$defs[r.$ref.split('/').at(-1)!].properties.operation.const);
    expect(ops.sort()).toEqual(['get_environment', 'get_run', 'get_workspace', 'list_accounts', 'list_environments', 'list_runs', 'list_workspaces']);
    expect(schema.$defs.ScalrRunsConfig.properties.include_names.default).toBe(false);
    expect(schema.$defs.ScalrRunsConfig.properties.workspace_id['x-dynamic-options'].depends_on).toEqual(['account_id', 'environment_id']);
    expect(schema.$defs.ScalrRunsConfig.properties.inputs).toBeUndefined();
    expect(schema.$defs.ScalrRunsConfig.properties.fields).toBeUndefined();
  });
  it('uses the integration icon and retains supplied canvas styles', () => {
    const Icon = ScalrNode.Icon;
    const filter = 'invert(1) drop-shadow(0 0 4px #aaaaaa55)';
    const html = renderToStaticMarkup(<Icon style={{ width: 48, height: 48, filter }} />);
    expect(html).toContain('/icons/scalr-brand.svg');
    expect(html).toContain('object-fit:contain');
    expect(html).toContain(`filter:${filter}`);
  });
});
