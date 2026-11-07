// Grocy schema, credential selection and official icon contract.
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeAll, describe, expect, it } from 'vitest';
import { GrocyNode } from '~/components/workflow/nodes/integrations/grocy';
import { NODE_SCHEMAS, loadNodeSchemas, getNodeCredentialInfo, isAgentToolProviderType } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
const TYPE = 'automation-grocy', FAMILY = 'grocy_api_key';
describe('Grocy native metadata', () => {
    beforeAll(() => loadNodeSchemas([TYPE]));
    it('uses actual header-key readers and four closed metadata schemas', () => {
        expect(getNodeCredentialInfo(TYPE)?.acceptedTypes).toEqual([FAMILY]);
        expect(getNodeCredentialInfo(TYPE)?.label).toBe('Grocy API Key');
        expect(getCredentialTypeFromSchemaTitle('GrocyAPIKeyCredential')).toBe(FAMILY);
        expect(isAgentToolProviderType(TYPE)).toBe(true);
        expect(GrocyNode.type).toBe(TYPE);
        const schema = NODE_SCHEMAS[TYPE], key = schema.$defs.GrocyAPIKeyCredential;
        expect(key.required).toEqual(expect.arrayContaining(['api_key', 'instance_url']));
        expect(key.properties.api_key['ui:widget']).toBe('password');
        expect(key['x-oauth-provider']).toBeUndefined();
        const ops = schema.properties.config.oneOf.map((r: { $ref: string }) => schema.$defs[r.$ref.split('/').at(-1)!].properties.operation.const);
        expect(ops.sort()).toEqual(['get_location', 'get_quantity_unit', 'list_locations', 'list_quantity_units']);
        for (const [config, id] of [['GrocyLocationConfig', 'location_id'], ['GrocyQuantityUnitConfig', 'quantity_unit_id']]) {
            const p = schema.$defs[config].properties;
            expect(p.include_names.default).toBe(false);
            expect(p.limit.default).toBe(100);
            expect(p.limit.minimum).toBe(1);
            expect(p.limit.maximum).toBe(100);
            expect(p[id]['x-dynamic-options'].auto_select_sole_option).toBe(true);
            expect(p[id]['x-dynamic-options'].depends_on).toBeUndefined();
            for (const field of ['page', 'offset', 'entity', 'url', 'headers', 'query', 'order', 'userfields', 'stock', 'api_key']) expect(p[field]).toBeUndefined();
        }
    });
    it('selects and removes only native saved header keys', () => {
        upsertCredentialsIntoCache([{ id: 'grocy-fixture', name: 'Fixture API key', credential_type: FAMILY, owned_by_me: true }]);
        expect(autoSelectCredentialFromCache(TYPE)).toEqual({ [FAMILY]: 'grocy-fixture' });
        removeCredentialsFromCache(['grocy-fixture']);
        expect(autoSelectCredentialFromCache(TYPE)).toEqual({});
    });
    it('preserves the original SVG and the supplied canvas filter', () => {
        const filter = 'grayscale(100%) brightness(0.4) drop-shadow(0 4px 12px #0004)';
        const html = renderToStaticMarkup(<GrocyNode.Icon style={{ width: 48, height: 48, filter }} />);
        expect(html).toContain('/icons/grocy-brand-vector.svg');
        expect(html).toContain('object-fit:contain');
        expect(html).toContain('filter:' + filter);
    });
});
