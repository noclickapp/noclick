// Prepared BoldSign credential discovery, selection and nested-save fixtures.
// Actual UI helpers use synthetic descriptors; no provider request is made.
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import schema from '~/schemas/nodes/boldsign.json';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { BoldSignNode } from '~/components/workflow/nodes/integrations/boldsign';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { invalidateCredentialsCache, setActiveCredentialWorkflow, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { createWorkflowNode, applyNodeUpdate, buildSaveConfig } from '~/lib/applyNodeUpdate';

beforeAll(() => loadNodeSchemas([BoldSignNode.type]));

describe('BoldSign native configuration', () => {
  beforeEach(() => { invalidateCredentialsCache(); setActiveCredentialWorkflow('owned-fixture'); });
  it('discovers both manual credential families with explicit issued environment and saved scope', () => {
    expect(NODE_SCHEMAS[BoldSignNode.type]).toBe(schema);
    expect(getNodeCredentialInfo(BoldSignNode.type)?.acceptedTypes).toEqual(['boldsign_api_key', 'boldsign_client_credentials']);
    expect(CREDENTIAL_TYPE_MAP.BoldSignCredential).toBe('boldsign_api_key');
    expect(CREDENTIAL_TYPE_MAP['BoldSign API Key']).toBe('boldsign_api_key');
    const cred = schema.$defs.BoldSignCredential;
    expect(cred.properties.api_key['ui:widget']).toBe('password');
    expect(cred.required).toContain('environment');
    expect(cred.properties.allowed_document_ids).toBeDefined();
    expect(cred.properties.allowed_contact_ids).toBeDefined();
    expect(cred.properties.allow_contact_create.default).toBe(false);
    expect(cred).not.toHaveProperty('x-oauth-provider');
    expect(cred).not.toHaveProperty('x-credential-type');
    expect(schema.$defs.BoldSignDocumentConfig.properties.document_id['x-dynamic-options'].searchable).toBe(true);
  });
  it('selects owned API keys without accepting other provider or shared descriptors', () => {
    upsertCredentialsIntoCache([{ id: 'owned-key', credential_type: 'boldsign_api_key', name: 'Owned key', owned_by_me: true },
      { id: 'shared-key', credential_type: 'boldsign_api_key', name: 'Shared key', owned_by_me: false },
      { id: 'other-key', credential_type: 'other_token', name: 'Other provider', owned_by_me: true }]);
    expect(autoSelectCredentialFromCache(BoldSignNode.type)).toEqual({ boldsign_api_key: 'owned-key' });
  });
  it('saves exact resource IDs, labels and credential attachment under nested config', () => {
    const created = createWorkflowNode('owned-node', BoldSignNode.type, { x: 0, y: 0 }, { operation: 'get_document_status', document_id: 'doc-owned-42' });
    const updated = applyNodeUpdate(created, { credentialIds: { boldsign_api_key: 'owned-key' }, config: { document_id__label: 'Owned fixture' } });
    const saved = buildSaveConfig(updated);
    expect(saved.operation).toBe('get_document_status');
    expect(saved.document_id).toBe('doc-owned-42');
    expect(saved.document_id__label).toBe('Owned fixture');
    expect(saved.credentialIds).toEqual({ boldsign_api_key: 'owned-key' });
    expect(updated.data).not.toHaveProperty('document_id');
  });
  it('retains the exact official developer SVG wordmark', () => {
    expect(createHash('sha256').update(readFileSync(resolve(process.cwd(), 'public/icons/boldsign.svg'))).digest('hex')).toBe('e2be2310a2ee765d944a9f8c1466e03ad31cd3b805ba21b9a4c464d6fce551e1');
  });
});

// Machine client credentials are entered manually; token exchange stays local.
it('offers both methods without requesting an OAuth callback', () => {
  const methods = credentialRequirements('automation-boldsign').map(methodFromRequirement);
  expect(methods.map(method => method.credential_type)).toEqual(['boldsign_api_key', 'boldsign_client_credentials']);
  expect(methods.map(method => method.method_kind)).toEqual(['api_key', 'api_key']);
  expect(methods.every(method => !method.is_oauth)).toBe(true);
  expect(schema.$defs.BoldSignClientCredentials.required).toEqual(expect.arrayContaining(['client_id', 'client_secret', 'scopes', 'environment']));
  expect(schema.$defs.BoldSignClientCredentials.properties.client_secret['ui:widget']).toBe('password');
});
