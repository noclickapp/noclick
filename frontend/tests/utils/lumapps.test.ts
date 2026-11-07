// LumApps self-registering schema, palette and credential wiring.
import { describe, expect, it, vi } from 'vitest';
import schema from '~/schemas/nodes/lumapps.json';
import { LumAppsNode } from '~/components/workflow/nodes/integrations/lumapps';
import { AVAILABLE_NODES } from '~/components/workflow/nodes/nodeRegistry';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
vi.mock('~/utils/credentialTypes', async () => ({ CREDENTIAL_TYPE_MAP: (await import('~/utils/credentialTypeMap')).CREDENTIAL_TYPE_MAP }));
vi.mock('~/lib/telemetry-errors', () => ({ reportInvariant: vi.fn() }));

describe('LumApps native credential and operation wiring', () => {
  it('shows the issued-token credential in the current schema/modal and palette', async () => {
    await loadNodeSchemas(['automation-lumapps']);
    const def = schema.$defs.LumAppsAccessTokenCredential;
    expect(def.title).toBe('LumApps Supplied Access Token');
    expect(getCredentialTypeFromSchemaTitle(def.title)).toBe('lumapps_access_token');
    expect(getCredentialTypeFromSchemaTitle('LumAppsAccessTokenCredential')).toBe('lumapps_access_token');
    expect(def.required).toEqual(expect.arrayContaining(['access_token', 'api_origin', 'customer_id', 'expires_at']));
    expect(def).not.toHaveProperty('x-oauth-provider');
    expect(getNodeCredentialInfo('automation-lumapps')?.acceptedTypes).toEqual(['lumapps_access_token']);
    expect(AVAILABLE_NODES.some(node => node.type === LumAppsNode.type)).toBe(true);
  });
  it('keeps scoped dependent resources and draft-only input contracts', () => {
    expect(schema.$defs.LumAppsGetContent.properties.content_id['x-dynamic-options']).toMatchObject({
      field_name: 'content_id', depends_on: ['instance_id'],
    });
    expect(schema.$defs.LumAppsCreateDraft.properties.source_content_id['x-resource-type']).toBe('lumapps_content');
    expect(schema.$defs.LumAppsCreateDraft.properties.operation['x-resource-id-path']).toBe('data.id');
    expect(schema.$defs.LumAppsCreateDraft.properties).not.toHaveProperty('status');
    expect(schema.$defs.LumAppsCreateDraft.properties).not.toHaveProperty('sendNotifications');
    expect(schema.$defs.LumAppsDeleteDraft.required).toContain('confirm_draft_delete');
    expect(schema.$defs.LumAppsListContent.properties.lang.default).toBe('en');
  });
});
