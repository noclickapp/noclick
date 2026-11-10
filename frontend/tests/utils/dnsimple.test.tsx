// Exercises DNSimple's generated schema, credential cache and canvas icon.
// Schema loading follows the same lazy-loading contract as the workflow UI.
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeAll, describe, expect, it } from 'vitest';
import DNSimpleIcon from '~/components/icons/DNSimpleIcon';
import { DNSimpleNode } from '~/components/workflow/nodes/integrations/dnsimple';
import { NODE_SCHEMAS, getNodeCredentialInfo, isAgentToolProviderType, loadNodeSchemas } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { cachedCredentialsOfType, upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
const TYPE = 'automation-dnsimple', FAMILY = 'dnsimple_account_token';
describe('DNSimple native metadata', () => {
  beforeAll(async () => { await loadNodeSchemas([TYPE]); });
  it('uses the actual account credential readers and four closed operations', () => {
    expect(getNodeCredentialInfo(TYPE)?.acceptedTypes).toEqual([FAMILY]);
    expect(getNodeCredentialInfo(TYPE)?.label).toBe('DNSimple');
    expect(getCredentialTypeFromSchemaTitle('DNSimpleAccountTokenCredential')).toBe(FAMILY);
    expect(isAgentToolProviderType(TYPE)).toBe(true);
    expect(DNSimpleNode.type).toBe(TYPE);
    const schema = NODE_SCHEMAS[TYPE], key = schema.$defs.DNSimpleAccountTokenCredential;
    expect(key.required).toEqual(expect.arrayContaining(['access_token', 'account_id']));
    expect(key.properties.access_token['ui:widget']).toBe('password');
    expect(key.properties.account_id.type).toBe('integer');
    expect(key.properties.environment.enum).toEqual(['production', 'sandbox']);
    expect(key['x-oauth-provider']).toBeUndefined();
    const ops = schema.properties.config.oneOf.map((r: { $ref: string }) => schema.$defs[r.$ref.split('/').at(-1)!].properties.operation.const);
    expect(ops.sort()).toEqual(['get_domain', 'get_zone', 'list_domains', 'list_zones']);
    const properties = schema.$defs.DNSimpleZoneConfig.properties;
    expect(properties.include_names.default).toBe(false);
    expect(properties.page.default).toBe(1);
    expect(properties.per_page.default).toBe(30);
    expect(properties.per_page.maximum).toBe(100);
    expect(properties.zone_name['x-dynamic-options'].depends_on).toEqual(['page', 'per_page', 'include_names']);
    expect(properties.zone_name['x-dynamic-options'].auto_select_sole_option).toBe(false);
    for (const name of ['records', 'content', 'account_id', 'access_token', 'url', 'headers', 'cursor', 'registrant_id', 'auto_renew']) expect(properties[name]).toBeUndefined();
  });
  it('selects and removes only the actual saved account-token family', () => {
    upsertCredentialsIntoCache([{ id: 'dnsimple-fixture', name: 'Fixture account token', credential_type: FAMILY, owned_by_me: true }]);
    expect(getNodeCredentialInfo(TYPE)?.acceptedTypes).toContain(FAMILY);
    expect(cachedCredentialsOfType(FAMILY)?.map(credential => credential.id)).toEqual(['dnsimple-fixture']);
    removeCredentialsFromCache(['dnsimple-fixture']);
    expect(cachedCredentialsOfType(FAMILY) ?? []).toEqual([]);
  });
  it('shows the original black SVG in light mode and its white copy in dark, under the supplied canvas filter', () => {
    const filter = 'grayscale(100%) brightness(0.4) drop-shadow(0 4px 12px #0004)';
    const html = renderToStaticMarkup(<DNSimpleIcon style={{ width: 48, height: 48, filter }} />);
    const [light, dark, ...more] = html.match(/<img[^>]*>/g) ?? [];
    expect(more).toEqual([]);
    expect(light).toContain('src="/icons/dnsimple.svg"');
    expect(light).toContain('class="dark:hidden"');
    expect(dark).toContain('src="/icons/dnsimple-dark.svg"');
    expect(dark).toContain('class="hidden dark:block"');
    for (const img of [light, dark]) {
      expect(img).toContain('object-fit:contain');
      expect(img).toContain(`filter:${filter}`);
    }
    expect(html).not.toContain('invert(');
  });
});

