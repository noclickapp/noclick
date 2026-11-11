// actual schema/Agent/credential/cache/icon native consumers.
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeAll, describe, expect, it } from 'vitest';
import STACKITDNSIcon from '~/components/icons/STACKITDNSIcon';
import { STACKITDNSNode } from '~/components/workflow/nodes/integrations/stackitdns';
import { NODE_SCHEMAS, getNodeCredentialInfo, isAgentToolProviderType, loadNodeSchemas } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
const TYPE = 'automation-stackitdns', FAMILY = 'stackitdns_access_token';
beforeAll(async () => { await loadNodeSchemas([TYPE]); });
describe('STACKIT DNS native metadata', () => {
  it('uses actual credential readers and four closed operations', () => {
    expect(getNodeCredentialInfo(TYPE)?.acceptedTypes).toEqual([FAMILY]);
    expect(getNodeCredentialInfo(TYPE)?.label).toBe('STACKIT DNS');
    expect(getCredentialTypeFromSchemaTitle('STACKITDNSAccessTokenCredential')).toBe(FAMILY);
    expect(isAgentToolProviderType(TYPE)).toBe(true);
    expect(STACKITDNSNode.type).toBe(TYPE);
    const schema = NODE_SCHEMAS[TYPE], key = schema.$defs.STACKITDNSAccessTokenCredential;
    expect(key.required).toEqual(expect.arrayContaining(['access_token', 'project_id']));
    expect(key.properties.access_token['ui:widget']).toBe('password');
    expect(key['x-oauth-provider']).toBeUndefined();
    expect(requirementsFromSchema(schema).map(req => methodFromRequirement(req).method_kind)).toEqual(['api_key']);
    const ops = schema.properties.config.oneOf.map((r: { $ref: string }) => schema.$defs[r.$ref.split('/').at(-1)!].properties.operation.const);
    expect(ops.sort()).toEqual(['get_rrset', 'get_zone', 'list_rrsets', 'list_zones']);
    const properties = schema.$defs.STACKITDNSRRSetConfig.properties;
    expect(properties.include_names.default).toBe(false);
    expect(properties.page.minimum).toBe(1);
    expect(properties.page_size.maximum).toBe(100);
    expect(properties.rrset_id['x-dynamic-options'].depends_on).toEqual(['project_id', 'zone_id', 'zone_catalog_page', 'page', 'page_size', 'include_names']);
    expect(properties.rrset_id['x-dynamic-options'].auto_select_sole_option).toBe(false);
    for (const name of ['records', 'RDATA', 'comment', 'acl', 'labels', 'url', 'headers', 'body', 'orderBy']) expect(properties[name]).toBeUndefined();
  });
  it('selects and removes only the actual saved family', () => {
    upsertCredentialsIntoCache([{ id: 'stackit-fixture', name: 'Fixture token', credential_type: FAMILY, owned_by_me: true }]);
    expect(autoSelectCredentialFromCache(TYPE)).toEqual({ [FAMILY]: 'stackit-fixture' });
    removeCredentialsFromCache(['stackit-fixture']);
    expect(autoSelectCredentialFromCache(TYPE)).toEqual({});
  });
  it('preserves original system-theme SVG and supplied canvas filter', () => {
    const filter = 'grayscale(100%) brightness(0.4) drop-shadow(0 4px 12px #0004)';
    const html = renderToStaticMarkup(<STACKITDNSIcon style={{ width: 48, height: 48, filter }} />);
    expect(html).toContain('/icons/stackitdns.svg');
    expect(html).toContain('object-fit:contain');
    expect(html).toContain(`filter:${filter}`);
    expect(html).toContain('--brand-invert:0');
    expect(html).not.toContain('invert(1)');
  });
});
