// Amplience native metadata and credential regression coverage.
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { AmplienceNode, AmplienceIcon } from '~/components/workflow/nodes/integrations/amplience';
import { NODE_SCHEMAS, loadNodeSchemas, getNodeCredentialInfo, isAgentToolProviderType } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn(async () => ({ credentials: [] })) }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(async () => null), set: vi.fn(async () => {}), delete: vi.fn() } }));
const TYPE = 'automation-amplience';
describe('native Amplience Content Management', () => {
  beforeAll(async () => { await loadNodeSchemas([TYPE]); });
  it('exposes both actual supplied-token families and twelve read operations', () => {
    const info = getNodeCredentialInfo(TYPE)!;
    expect(info.acceptedTypes).toEqual(['amplience_pat', 'amplience_access_token']);
    expect(info.label).toBe('Amplience');
    expect(getCredentialTypeFromSchemaTitle('AmpliencePATCredential')).toBe('amplience_pat');
    expect(getCredentialTypeFromSchemaTitle('AmplienceAccessTokenCredential')).toBe('amplience_access_token');
    expect(isAgentToolProviderType(TYPE)).toBe(true);
    expect(AmplienceNode.type).toBe(TYPE);
    expect(credentialRequirements(TYPE).map(methodFromRequirement).map(m => m.method_kind)).toEqual(['api_key', 'api_key']);
    const schema = NODE_SCHEMAS[TYPE];
    const pat = schema.$defs.AmpliencePATCredential;
    const access = schema.$defs.AmplienceAccessTokenCredential;
    expect(pat.required).toEqual(expect.arrayContaining(['token', 'reference_hub_id']));
    expect(pat.properties.token['ui:widget']).toBe('password');
    expect(pat.properties.expires_at).toBeUndefined();
    expect(access.required).toContain('expires_at');
    expect(access['x-oauth-provider']).toBeUndefined();
    const ops = schema.properties.config.oneOf.map((r: { $ref: string }) => schema.$defs[r.$ref.split('/').at(-1)!].properties.operation.const);
    expect(ops.sort()).toEqual(['check_connection', 'get_content_item', 'get_content_type', 'get_folder', 'get_hub', 'get_repository', 'list_content_items', 'list_content_types', 'list_folders', 'list_hubs', 'list_repositories', 'list_subfolders'].sort());
    expect(schema.$defs.AmplienceListContentItemsConfig.properties.include_names.default).toBe(false);
    expect(schema.$defs.AmplienceListContentItemsConfig.properties.size.maximum).toBe(100);
    expect(schema.$defs.AmplienceGetContentItemConfig.properties.repository_id['x-dynamic-options'].depends_on).toBe('hub_id');
    expect(schema.$defs.AmplienceGetContentItemConfig.properties.content_item_id['x-dynamic-options'].depends_on).toBe('repository_id');
  });
  it('selects saved credentials through the real provider schema and forgets removed rows', () => {
    const families = ['amplience_pat', 'amplience_access_token'];
    upsertCredentialsIntoCache(families.map((credential_type, i) => ({ id: `amplience-fixture-${i}`, name: 'Fixture token', credential_type, owned_by_me: true })));
    // Existing native cache selection chooses the primary declared family;
    // the credential UI separately admits the supplied access-token family.
    expect(autoSelectCredentialFromCache(TYPE)).toEqual({ amplience_pat: 'amplience-fixture-0' });
    removeCredentialsFromCache(['amplience-fixture-0', 'amplience-fixture-1']);
    expect(autoSelectCredentialFromCache(TYPE)).toEqual({});
  });
  it('preserves the unmodified vendor mark and actual supplied canvas filter', () => {
    const filter = 'grayscale(100%) brightness(0.4) drop-shadow(0px 1px 2px #000)';
    const html = renderToStaticMarkup(<AmplienceIcon style={{ width: 48, height: 48, filter }} />);
    expect(html).toContain('/icons/amplience.svg');
    expect(html).toContain('object-fit:contain');
    expect(html).toContain(`filter:${filter}`);
  });
});
