// Covers AccuLynx's generated native schema, credential discovery and owned selection.
// Only socket/cache/UI boundaries are synthetic; the provider and FlowCanvas remain unverified.
import { afterEach, expect, it, vi } from 'vitest';
import schema from '~/schemas/nodes/acculynx.json';
import { AccuLynxNode } from '~/components/workflow/nodes/AccuLynxNode';
import { filterConfigForExecution, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

const boundary = vi.hoisted(() => ({ send: vi.fn(), get: vi.fn(), set: vi.fn(), delete: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: boundary.send }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: boundary }));
vi.mock('~/components/workflow/nodes/base/AutomationNode', () => ({ default: () => null }));
vi.mock('~/components/workflow/nodes/nodeRegistry', async () => ({ AVAILABLE_NODES: [(await import('~/components/workflow/nodes/AccuLynxNode')).AccuLynxNode] }));
const selection = await import('~/utils/credentialAutoSelect');
afterEach(() => { selection.invalidateCredentialsCache(); boundary.send.mockReset(); });

it('discovers the issued-key family and actual company binding without a fake OAuth app', () => {
    expect(getNodeCredentialInfo(AccuLynxNode.type)?.acceptedTypes).toEqual(['acculynx_api_key']);
    const credential = schema.$defs.AccuLynxAPIKeyCredential;
    expect(credential.properties.api_key['ui:widget']).toBe('password');
    expect(credential.required).toEqual(expect.arrayContaining(['api_key', 'company_id']));
    expect((credential as Record<string, unknown>)['x-oauth-provider']).toBeUndefined();
    expect(credential.properties).not.toHaveProperty('location_id');
    expect(humanizeCredentialLabel('AccuLynxAPIKey')).toBe('AccuLynx API Key');
});

it('selects only an owned, current matching-family credential from the actual cache', () => {
    selection.upsertCredentialsIntoCache([
        { id: 'foreign', credential_type: 'api_key', name: 'Foreign', owned_by_me: true },
        { id: 'revoked', credential_type: 'acculynx_api_key', name: 'Revoked', owned_by_me: true, revoked_at: '2026-10-06T00:00:00Z' },
        { id: 'owned', credential_type: 'acculynx_api_key', name: 'Owned', owned_by_me: true },
    ]);
    expect(selection.autoSelectCredentialFromCache(AccuLynxNode.type)).toEqual({ acculynx_api_key: 'owned' });
    expect(boundary.send).not.toHaveBeenCalled();
});

it('keeps native lead creation typed and excludes money, messages, assignment and raw endpoints', () => {
    const config = filterConfigForExecution(AccuLynxNode.type, { operation: 'create_unassigned_lead', contact_id: '00000000-0000-4000-8000-000000000002', notes: 'Owned fixture', confirm_crm_change: true, representative_id: 'foreign', payment: {}, message: 'send', endpoint: '/orders' });
    expect(config).toMatchObject({ operation: 'create_unassigned_lead', contact_id: '00000000-0000-4000-8000-000000000002', notes: 'Owned fixture', confirm_crm_change: true });
    for (const key of ['representative_id', 'payment', 'message', 'endpoint']) expect(config).not.toHaveProperty(key);
    expect(schema.$defs.CreateLead.properties.contact_id['x-dynamic-options'].field_name).toBe('contact_id');
    expect(schema.$defs.Jobs.properties.page_size.maximum).toBe(25);
});
