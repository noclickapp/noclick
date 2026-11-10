// Pulumi schema, credential selection and icon contract on staging helpers.
// Load the schema before reading its generated credential and operation metadata.
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeAll, describe, expect, it } from 'vitest';
import { PulumiIcon, PulumiNode } from '~/components/workflow/nodes/integrations/pulumi';
import { NODE_SCHEMAS, loadNodeSchemas, getNodeCredentialInfo, isAgentToolProviderType } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
const TYPE = 'automation-pulumi', FAMILY = 'pulumi_access_token';
describe('Pulumi Cloud native stack metadata', () => {
  beforeAll(() => loadNodeSchemas([TYPE]));
  it('uses actual credential readers and four closed operations', () => {
    expect(getNodeCredentialInfo(TYPE)?.acceptedTypes).toEqual([FAMILY]);
    expect(getNodeCredentialInfo(TYPE)?.label).toBe('Pulumi Cloud Access Token');
    expect(getCredentialTypeFromSchemaTitle('PulumiAccessTokenCredential')).toBe(FAMILY);
    expect(isAgentToolProviderType(TYPE)).toBe(true);
    expect(PulumiNode.type).toBe(TYPE);
    const schema = NODE_SCHEMAS[TYPE], key = schema.$defs.PulumiAccessTokenCredential;
    expect(key.required).toEqual(expect.arrayContaining(['access_token', 'organization']));
    expect(key.properties.access_token['ui:widget']).toBe('password');
    expect(key['x-oauth-provider']).toBeUndefined();
    const ops = schema.properties.config.oneOf.map((r: { $ref: string }) => schema.$defs[r.$ref.split('/').at(-1)!].properties.operation.const);
    expect(ops.sort()).toEqual(['get_resource_count', 'get_stack', 'list_downstream_references', 'list_stacks']);
    const properties = schema.$defs.PulumiResourceCountConfig.properties;
    expect(properties.include_names.default).toBe(false);
    expect(properties.stack_name['x-dynamic-options'].depends_on).toEqual(['project_name', 'include_names']);
    expect(properties.stack_name['x-dynamic-options'].auto_select_sole_option).toBe(false);
    expect(properties.max_results.maximum).toBe(100);
    for (const name of ['url', 'headers', 'body', 'tags', 'resources', 'outputs', 'requestedByToken', 'roleID']) expect(properties[name]).toBeUndefined();
  });
  it('selects and removes only the native saved row', () => {
    upsertCredentialsIntoCache([{ id: 'pulumi-fixture', name: 'Fixture token', credential_type: FAMILY, owned_by_me: true }]);
    expect(autoSelectCredentialFromCache(TYPE)).toEqual({ [FAMILY]: 'pulumi-fixture' });
    removeCredentialsFromCache(['pulumi-fixture']);
    expect(autoSelectCredentialFromCache(TYPE)).toEqual({});
  });
  it('keeps original full-color art and supplied disabled/shadow filter', () => {
    const filter = 'grayscale(100%) brightness(0.4) drop-shadow(0 4px 12px #0004)';
    const html = renderToStaticMarkup(<PulumiIcon style={{ width: 48, height: 48, filter }} />);
    expect(html).toContain('/icons/pulumi.svg');
    expect(html).toContain('object-fit:contain');
    expect(html).toContain(`filter:${filter}`);
    expect(html).not.toContain('brand-invert');
    expect(html).not.toContain('invert(1)');
  });
});
