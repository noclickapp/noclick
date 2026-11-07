// Hivelocity schema, credential selection, Agent and icon contracts.
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeAll, describe, expect, it } from 'vitest';
import { HivelocityNode } from '~/components/workflow/nodes/integrations/hivelocity';
import { NODE_SCHEMAS, loadNodeSchemas, getNodeCredentialInfo, isAgentToolProviderType } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
const TYPE = 'automation-hivelocity', FAMILY = 'hivelocity_api_key';
describe('Hivelocity native device metadata', () => {
  beforeAll(() => loadNodeSchemas([TYPE]));
  it('reads actual credential definitions/only two operations/defaults', () => {
    expect(getNodeCredentialInfo(TYPE)?.acceptedTypes).toEqual([FAMILY]);
    expect(getNodeCredentialInfo(TYPE)?.label).toBe('Hivelocity API Key');
    expect(getCredentialTypeFromSchemaTitle('HivelocityAPIKeyCredential')).toBe(FAMILY);
    expect(isAgentToolProviderType(TYPE)).toBe(true);
    expect(HivelocityNode.type).toBe(TYPE);
    const schema = NODE_SCHEMAS[TYPE], key = schema.$defs.HivelocityAPIKeyCredential;
    expect(key.required).toEqual(expect.arrayContaining(['api_key', 'reference_device_id']));
    expect(key.properties.api_key['ui:widget']).toBe('password');
    expect(key.properties.refresh_token).toBeUndefined();
    expect(key.properties.base_url).toBeUndefined();
    expect(key['x-oauth-provider']).toBeUndefined();
    const ops = schema.properties.config.oneOf.map((r: { $ref: string }) => schema.$defs[r.$ref.split('/').at(-1)!].properties.operation.const);
    expect(ops.sort()).toEqual(['get_device', 'list_devices']);
    expect(schema.$defs.HivelocityDeviceConfig.properties.include_names.default).toBe(false);
    expect(schema.$defs.HivelocityDeviceConfig.properties.device_id['x-dynamic-options'].field_name).toBe('device_id');
    expect(schema.$defs.HivelocityDevicesConfig.properties.page).toBeUndefined();
    expect(schema.$defs.HivelocityDevicesConfig.properties.fields).toBeUndefined();
    expect(schema.$defs.HivelocityDevicesConfig.properties.rack_id).toBeUndefined();
  });
  it('uses native auto-selection and removes unavailable rows', () => {
    upsertCredentialsIntoCache([{ id: 'hivelocity-fixture', name: 'Fixture key', credential_type: FAMILY, owned_by_me: true }]);
    expect(autoSelectCredentialFromCache(TYPE)).toEqual({ [FAMILY]: 'hivelocity-fixture' });
    removeCredentialsFromCache(['hivelocity-fixture']);
    expect(autoSelectCredentialFromCache(TYPE)).toEqual({});
  });
  it('renders the official canvas artwork and preserves the supplied filter', () => {
    const filter = 'grayscale(100%) brightness(0.4)';
    const html = renderToStaticMarkup(<HivelocityNode.Icon style={{ width: 48, height: 48, filter }} />);
    expect(html).toContain('/icons/hivelocity-preferred-brand.svg');
    expect(html).toContain('object-fit:contain');
    expect(html).toContain(`filter:${filter}`);
  });
});
