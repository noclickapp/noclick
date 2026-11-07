// Native schema, selection and supplied-filter regressions.
// These fixtures cover the integration's real frontend readers after generation.
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeAll, describe, expect, it } from 'vitest';
import { NorthflankIcon } from '~/components/workflow/nodes/integrations/northflank';
import { loadNodeSchemas, NODE_SCHEMAS, getNodeCredentialInfo, isAgentToolProviderType } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
const TYPE = 'automation-northflank', FAMILY = 'northflank_api_token';
describe('native Northflank', () => {
  beforeAll(() => loadNodeSchemas([TYPE]));
  it('loads native credentials, typed operations and parent-dependent selectors', () => {
    expect(getNodeCredentialInfo(TYPE)?.acceptedTypes).toEqual([FAMILY]);
    expect(getNodeCredentialInfo(TYPE)?.label).toBe('Northflank API Token');
    expect(getCredentialTypeFromSchemaTitle('NorthflankAPITokenCredential')).toBe(FAMILY);
    expect(getCredentialTypeFromSchemaTitle('Northflank API Token')).toBe(FAMILY);
    expect(isAgentToolProviderType(TYPE)).toBe(true);
    const schema = NODE_SCHEMAS[TYPE];
    expect(schema.$defs.NorthflankAPITokenCredential.required).toEqual(expect.arrayContaining(['api_token', 'target']));
    expect(schema.$defs.NorthflankAPITokenCredential.properties.api_token['ui:widget']).toBe('password');
    expect(schema.$defs.NorthflankAPITokenCredential['x-oauth-provider']).toBeUndefined();
    const ops = schema.properties.config.oneOf.map((r: { $ref: string }) => schema.$defs[r.$ref.split('/').at(-1)!].properties.operation.const);
    expect(ops).toHaveLength(16);
    expect(ops).toContain('delete_project');
    expect(ops).not.toContain('start_build');
    expect(ops).not.toContain('run_job');
    expect(schema.$defs.NorthflankGetServiceConfig.properties.service_id['x-dynamic-options'].depends_on).toBe('project_id');
    expect(schema.$defs.NorthflankGetRunConfig.properties.run_id['x-dynamic-options'].depends_on).toBe('job_id');
    expect(schema.$defs.NorthflankDeleteProjectConfig.required).toEqual(expect.arrayContaining(['project_id', 'expected_project_uid', 'confirm_owned_empty_project']));
  });
  it('uses the actual native auto-selection map and removes revoked entries', () => {
    upsertCredentialsIntoCache([{ id: 'northflank-fixture', name: 'Fixture token', credential_type: FAMILY, owned_by_me: true }]);
    expect(autoSelectCredentialFromCache(TYPE)).toEqual({ [FAMILY]: 'northflank-fixture' });
    removeCredentialsFromCache(['northflank-fixture']);
    expect(autoSelectCredentialFromCache(TYPE)).toEqual({});
  });
  it('preserves the official colored mark and supplied disabled filter', () => {
    const filter = 'grayscale(100%) brightness(0.4) drop-shadow(0 0 3px black)';
    const html = renderToStaticMarkup(<NorthflankIcon style={{ width: 48, height: 48, filter }} />);
    expect(html).toContain('/icons/northflank.svg');
    expect(html).toContain('object-fit:contain');
    expect(html).toContain(`filter:${filter}`);
    expect(html).not.toContain('brand-mono');
    expect(html).not.toContain('invert(1)');
  });
});
