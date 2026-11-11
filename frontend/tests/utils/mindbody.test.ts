// Unrun native Mindbody registration, manual-form and selection fixtures.
// These exercise actual schema consumers and nested node saves with synthetic cache data.
// They make no provider request.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));

import schema from '~/schemas/nodes/mindbody.json';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { invalidateCredentialsCache, setActiveCredentialWorkflow, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { createWorkflowNode, applyNodeUpdate, buildSaveConfig } from '~/lib/applyNodeUpdate';
import { MindbodyNode } from '~/components/workflow/nodes/integrations/mindbody';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';

describe('Mindbody native source wiring', () => {
  beforeEach(async () => {
    await loadNodeSchemas([MindbodyNode.type]);
    invalidateCredentialsCache();
    setActiveCredentialWorkflow('owned-test-workflow');
  });
  it('uses the native manual family and human label without OAuth metadata', () => {
    expect(MindbodyNode.type).toBe('automation-mindbody');
    expect(MindbodyNode.label).toBe('Mindbody');
    expect(NODE_SCHEMAS[MindbodyNode.type]).toBe(schema);
    expect(CREDENTIAL_TYPE_MAP.MindbodyAPIKeyCredential).toBe('mindbody_api_key');
    expect(CREDENTIAL_TYPE_MAP['Mindbody Public API']).toBe('mindbody_api_key');
    expect(getNodeCredentialInfo(MindbodyNode.type)).toBeTruthy();
    const credential = schema.$defs.MindbodyAPIKeyCredential;
    expect(credential.title).toBe('Mindbody Public API');
    expect(credential.properties.api_key['ui:widget']).toBe('password');
    expect(credential).not.toHaveProperty('x-oauth-provider');
    expect(credential.properties.site_id.type).toBe('integer');
    expect(credential.properties.user_authorization.anyOf).toContainEqual({ type: 'null' });
  });
  it('selects an owned key and never selects injected owner descriptors', () => {
    upsertCredentialsIntoCache([{ id: 'owned-key', credential_type: 'mindbody_api_key', name: 'Owned key', owned_by_me: true }]);
    upsertCredentialsIntoCache([{ id: 'shared-owner-key', credential_type: 'mindbody_api_key', name: 'Owner key', owned_by_me: false }]);
    expect(autoSelectCredentialFromCache(MindbodyNode.type)).toEqual({ mindbody_api_key: 'owned-key' });
  });
  it('preserves false consent and operation config through the real save lens', () => {
    const created = createWorkflowNode('owned-node', MindbodyNode.type, { x: 0, y: 0 }, { operation: 'update_client_preferences', client_id: 'owned-client', active: false, test: true, promotional_emails: false });
    const updated = applyNodeUpdate(created, { credentialIds: { mindbody_api_key: 'owned-key' }, config: { schedule_texts: true } });
    expect((updated.data.config as Record<string, unknown>).promotional_emails).toBe(false);
    expect(updated.data).not.toHaveProperty('promotional_emails');
    const saved = buildSaveConfig(updated);
    expect(saved.promotional_emails).toBe(false);
    expect(saved.schedule_texts).toBe(true);
    expect(saved.credentialIds).toEqual({ mindbody_api_key: 'owned-key' });
  });
  it('preserves the complete official SVG bytes', () => {
    const bytes = readFileSync(resolve(process.cwd(), 'public/icons/mindbody.svg'));
    expect(createHash('sha256').update(bytes).digest('hex')).toBe('afa6ada776545ce8839f278ff2877a285b07643b55b6ef5796550013faa497a8');
    expect(bytes.toString()).toContain('viewBox="0 0 911.98 191.2"');
  });
});

