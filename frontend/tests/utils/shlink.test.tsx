// Shlink discovery, credential metadata, schema and original icon consumers.
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeAll, describe, expect, it } from 'vitest';
import { ShlinkNode, ShlinkIcon } from '~/components/workflow/nodes/integrations/shlink';
import { NODE_SCHEMAS, getNodeCredentialInfo, isAgentToolProviderType, loadNodeSchemas } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
const TYPE = 'automation-shlink', FAMILY = 'shlink_api_key';
describe('Shlink native metadata', () => {
    beforeAll(async () => { await loadNodeSchemas([TYPE]); });
    it('uses actual credential readers, native operation schema and parent context', () => {
        expect(getNodeCredentialInfo(TYPE)?.acceptedTypes).toEqual([FAMILY]);
        expect(getNodeCredentialInfo(TYPE)?.label).toBe('Shlink API Key');
        expect(getCredentialTypeFromSchemaTitle('ShlinkAPIKeyCredential')).toBe(FAMILY);
        expect(isAgentToolProviderType(TYPE)).toBe(true);
        expect(ShlinkNode.type).toBe(TYPE);
        const schema = NODE_SCHEMAS[TYPE], key = schema.$defs.ShlinkAPIKeyCredential;
        expect(key.required).toEqual(expect.arrayContaining(['api_key', 'instance_url']));
        expect(key.properties.api_key['ui:widget']).toBe('password');
        expect(key['x-oauth-provider']).toBeUndefined();
        const ops = schema.properties.config.oneOf.map((r: { $ref: string }) => schema.$defs[r.$ref.split('/').at(-1)!].properties.operation.const);
        expect(ops.sort()).toEqual(['get_short_url', 'list_domains', 'list_short_urls', 'list_tags']);
        const properties = schema.$defs.ShlinkShortUrlConfig.properties;
        expect(properties.include_names.default).toBe(false);
        expect(schema.$defs.ShlinkShortUrlConfig.required).toContain('domain');
        expect(properties.domain.default).toBeUndefined();
        expect(properties.items_per_page.maximum).toBe(100);
        expect(properties.short_code['x-dynamic-options'].depends_on).toBe('domain');
        expect(properties.short_code['x-dynamic-options'].auto_select_sole_option).toBe(false);
        for (const name of ['url', 'longUrl', 'shortUrl', 'headers', 'visits', 'cursor', 'redirects', 'api_key']) expect(properties[name]).toBeUndefined();
    });
    it('preserves the original blue asset and actual canvas filter', () => {
        const filter = 'grayscale(100%) brightness(0.4) drop-shadow(0 4px 12px #0004)';
        const html = renderToStaticMarkup(<ShlinkIcon style={{ width: 48, height: 48, filter }} />);
        expect(html).toContain('/icons/shlink.svg');
        expect(html).toContain('object-fit:contain');
        expect(html).toContain('filter:' + filter);
        expect(html).not.toContain('invert(');
    });
});
