// Exercises Svix's generated native schema, credential label and current selection.
// Socket, cache and node rendering boundaries are synthetic; canvas proof is deferred.
import { afterEach, expect, it, vi } from 'vitest';
import schema from '~/schemas/nodes/svix.json';
import { SvixNode } from '~/components/workflow/nodes/integrations/svix';
import { filterConfigForExecution, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

const boundary = vi.hoisted(() => ({ send: vi.fn(), get: vi.fn(), set: vi.fn(), delete: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: boundary.send }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: boundary }));
vi.mock('~/components/workflow/nodes/base/AutomationNode', () => ({ default: () => null }));
vi.mock('~/components/workflow/nodes/nodeRegistry', async () => ({ AVAILABLE_NODES: [(await import('~/components/workflow/nodes/integrations/svix')).SvixNode] }));
const selection = await import('~/utils/credentialAutoSelect');
const { autoSelectCredentialFromCache } = await import('~/utils/credentialAutoSelectForNode');
await loadNodeSchemas(['automation-svix']);
afterEach(() => { selection.invalidateCredentialsCache(); boundary.send.mockReset(); });

it('discovers a regional environment key without an invented OAuth app', () => {
    expect(getNodeCredentialInfo(SvixNode.type)?.acceptedTypes).toEqual(['svix_api_key']);
    const credential = schema.$defs.SvixAPIKeyCredential;
    expect(credential.required).toEqual(expect.arrayContaining(['region', 'api_key']));
    expect(credential.properties.region.enum).toEqual(['us', 'eu', 'ca', 'au', 'in']);
    expect(credential.properties.api_key['ui:widget']).toBe('password');
    expect((credential as Record<string, unknown>)['x-oauth-provider']).toBeUndefined();
    expect(credential.properties).not.toHaveProperty('refresh_token');
    expect(humanizeCredentialLabel('SvixAPIKey')).toBe('Svix API Key');
});

it('selects only the owned unrevoked Svix family', () => {
    const revoked = { id: 'revoked', credential_type: 'svix_api_key', name: 'Revoked', owned_by_me: true, revoked_at: '2026-10-06T00:00:00Z' };
    selection.upsertCredentialsIntoCache([
        { id: 'foreign', credential_type: 'api_key', name: 'Foreign', owned_by_me: true },
        revoked,
        { id: 'owned', credential_type: 'svix_api_key', name: 'Owned', owned_by_me: true },
    ]);
    expect(autoSelectCredentialFromCache(SvixNode.type)).toEqual({ svix_api_key: 'owned' });
    expect(boundary.send).not.toHaveBeenCalled();
});

it('keeps parent scopes and filters fields from other operations', () => {
    const app = 'app_' + 'A'.repeat(27), message = 'msg_' + 'C'.repeat(27);
    const config = filterConfigForExecution(SvixNode.type, { operation: 'list_message_attempts', application_id: app,
        message_id: message, delivery_status: 4, page_size: 25, expected_name: 'Previous application',
        confirm_metadata_change: true });
    expect(config).toMatchObject({ operation: 'list_message_attempts', application_id: app, message_id: message, delivery_status: 4, page_size: 25 });
    for (const key of ['expected_name', 'confirm_metadata_change']) expect(config).not.toHaveProperty(key);
    const fields = schema.$defs.ListMessageAttempts.properties;
    for (const key of ['with_content', 'replay', 'payload', 'endpoint']) expect(fields).not.toHaveProperty(key);
    expect(schema.$defs.GetAttempt.properties.attempt_id['x-dynamic-options'].depends_on).toBe('message_id');
    expect(schema.$defs.GetAttempt.properties.message_id['x-dynamic-options'].depends_on).toBe('application_id');
    expect(schema.$defs.ListApplications.properties.page_size.maximum).toBe(250);
    expect(schema.$defs.ArchiveEventType.properties.operation['x-read-only']).toBe(false);
});
