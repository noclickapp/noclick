// Prepared Bookwhen credential discovery, parent picker and nested-save regressions.
// These real UI helpers use synthetic descriptors and do not request provider data.
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import schema from '~/schemas/nodes/bookwhen.json';
import { BookwhenNode } from '~/components/workflow/nodes/integrations/bookwhen';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, loadNodeSchemas, NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { invalidateCredentialsCache, setActiveCredentialWorkflow, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { createWorkflowNode, applyNodeUpdate, buildSaveConfig } from '~/lib/applyNodeUpdate';

describe('Bookwhen native configuration', () => {
  beforeAll(() => loadNodeSchemas([BookwhenNode.type]));
  beforeEach(() => { invalidateCredentialsCache(); setActiveCredentialWorkflow('owned-test-workflow'); });
  it('discovers a masked supplied token without password or OAuth fields', () => {
    expect(NODE_SCHEMAS[BookwhenNode.type]).toBe(schema);
    expect(getNodeCredentialInfo(BookwhenNode.type)).toBeTruthy();
    expect(CREDENTIAL_TYPE_MAP.BookwhenAPITokenCredential).toBe('bookwhen_api_token');
    expect(CREDENTIAL_TYPE_MAP['Bookwhen API Token']).toBe('bookwhen_api_token');
    const form = schema.$defs.BookwhenAPITokenCredential;
    expect(form.required).toContain('api_token');
    expect(form.properties.api_token['ui:widget']).toBe('password');
    expect(form.properties).not.toHaveProperty('password');
    expect(form).not.toHaveProperty('x-oauth-provider');
    expect(schema.$defs.BookwhenGetTicketConfig.properties.ticket_id['x-dynamic-options'].depends_on).toBe('event_id');
  });
  it('selects an owned token and excludes shared or foreign descriptors', () => {
    upsertCredentialsIntoCache([{ id: 'owned-key', credential_type: 'bookwhen_api_token', name: 'Schedule fixture', owned_by_me: true },
      { id: 'shared-key', credential_type: 'bookwhen_api_token', name: 'Shared schedule', owned_by_me: false },
      { id: 'other-key', credential_type: 'other_token', name: 'Other provider', owned_by_me: true }]);
    expect(autoSelectCredentialFromCache(BookwhenNode.type)).toEqual({ bookwhen_api_token: 'owned-key' });
  });
  it('keeps event and ticket IDs, labels and selected credential in the saved config', () => {
    const created = createWorkflowNode('owned-node', BookwhenNode.type, { x: 0, y: 0 }, { operation: 'get_ticket', event_id: 'ev-owned', ticket_id: 'ti-owned' });
    const updated = applyNodeUpdate(created, { credentialIds: { bookwhen_api_token: 'owned-key' }, config: { event_id__label: 'Owned event', ticket_id__label: 'Owned ticket' } });
    const saved = buildSaveConfig(updated);
    expect(saved.operation).toBe('get_ticket');
    expect(saved.event_id).toBe('ev-owned');
    expect(saved.ticket_id).toBe('ti-owned');
    expect(saved.event_id__label).toBe('Owned event');
    expect(saved.ticket_id__label).toBe('Owned ticket');
    expect(saved.credentialIds).toEqual({ bookwhen_api_token: 'owned-key' });
    expect(updated.data).not.toHaveProperty('ticket_id');
  });
  it('keeps exact complete official API wordmark bytes', () => {
    expect(createHash('sha256').update(readFileSync(resolve(process.cwd(), 'public/icons/bookwhen.svg'))).digest('hex')).toBe('3f747e2f72eea03a99feb9785c30f3217c15308567917e9e2b8f2ca84a4be90e');
  });
});
