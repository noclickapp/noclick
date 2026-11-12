// UNRUN actual schema/Agent/credential/cache/icon consumers, not implementation stand-ins.
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeAll, describe, expect, it } from 'vitest';
import { ForgejoNode } from '~/components/workflow/nodes/integrations/forgejo';
import { NODE_SCHEMAS, getNodeCredentialInfo, isAgentToolProviderType, loadNodeSchemas } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
const TYPE = 'automation-forgejo', FAMILY = 'forgejo_pat';
describe('Forgejo native metadata', () => {
  beforeAll(() => loadNodeSchemas([TYPE]));
  it('uses actual credential readers and five closed operations', () => {
    expect(getNodeCredentialInfo(TYPE)?.acceptedTypes).toEqual([FAMILY]);
    expect(getNodeCredentialInfo(TYPE)?.label).toBe('Forgejo Account');
    expect(getCredentialTypeFromSchemaTitle('ForgejoPATCredential')).toBe(FAMILY);
    expect(isAgentToolProviderType(TYPE)).toBe(true);
    expect(ForgejoNode.type).toBe(TYPE);
    const schema = NODE_SCHEMAS[TYPE], key = schema.$defs.ForgejoPATCredential;
    expect(key.required).toEqual(expect.arrayContaining(['access_token', 'instance_url']));
    expect(key.properties.access_token['ui:widget']).toBe('password');
    expect(key['x-oauth-provider']).toBeUndefined();
    const ops = schema.properties.config.oneOf.map((r: { $ref: string }) => schema.$defs[r.$ref.split('/').at(-1)!].properties.operation.const);
    expect(ops.sort()).toEqual(['get_issue', 'get_repository', 'get_user', 'list_issues', 'list_repositories']);
    const properties = schema.$defs.ForgejoIssueConfig.properties;
    expect(properties.include_names.default).toBe(false);
    expect(properties.page.minimum).toBe(1);
    expect(properties.limit.maximum).toBe(100);
    expect(properties.state.default).toBe('open');
    expect(properties.issue_index['x-dynamic-options'].depends_on).toEqual(['owner', 'repo_name', 'repo_catalog_page', 'limit', 'include_names', 'state', 'page']);
    expect(properties.issue_index['x-dynamic-options'].auto_select_sole_option).toBe(false);
    for (const name of ['body', 'labels', 'assignees', 'url', 'headers', 'q', 'detailed', 'token', 'pull_request']) expect(properties[name]).toBeUndefined();
  });
  it('selects and removes only the real saved native family', () => {
    upsertCredentialsIntoCache([{ id: 'forgejo-fixture', name: 'Fixture PAT', credential_type: FAMILY, owned_by_me: true }]);
    expect(autoSelectCredentialFromCache(TYPE)).toEqual({ [FAMILY]: 'forgejo-fixture' });
    removeCredentialsFromCache(['forgejo-fixture']);
    expect(autoSelectCredentialFromCache(TYPE)).toEqual({});
  });
  it('preserves exact official artwork and supplied canvas filter', () => {
    const filter = 'grayscale(100%) brightness(0.4) drop-shadow(0 4px 12px #0004)';
    const Icon = ForgejoNode.Icon as React.ComponentType<{ style?: React.CSSProperties }>;
    const html = renderToStaticMarkup(<Icon style={{ width: 48, height: 48, filter }} />);
    expect(html).toContain('/icons/forgejo.svg');
    expect(html).toContain('object-fit:contain');
    expect(html).toContain(`filter:${filter}`);
    expect(html).not.toContain('brand-invert');
    expect(html).not.toContain('invert(');
  });
});
