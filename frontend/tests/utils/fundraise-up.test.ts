// Fundraise Up schema, saved-key selection and nested-save regressions.
// Real UI consumers use synthetic credentials without a provider request.
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import schema from '~/schemas/nodes/fundraise-up.json';
import { FundraiseUpNode } from '~/components/workflow/nodes/integrations/fundraise-up';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadAllNodeSchemas } from '~/utils/nodeSchemas';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { invalidateCredentialsCache, setActiveCredentialWorkflow, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { createWorkflowNode, applyNodeUpdate, buildSaveConfig } from '~/lib/applyNodeUpdate';

describe('Fundraise Up native configuration', () => {
  beforeAll(async () => { await loadAllNodeSchemas(); });
  beforeEach(() => { invalidateCredentialsCache(); setActiveCredentialWorkflow('owned-test-workflow'); });
  it('discovers manual Bearer form with required mode and account fence', () => {
    expect(NODE_SCHEMAS[FundraiseUpNode.type]).toBe(schema);
    expect(getNodeCredentialInfo(FundraiseUpNode.type)).toBeTruthy();
    expect(CREDENTIAL_TYPE_MAP.FundraiseUpAPIKeyCredential).toBe('fundraise_up_api_key');
    expect(CREDENTIAL_TYPE_MAP['Fundraise Up API Key']).toBe('fundraise_up_api_key');
    const credential = schema.$defs.FundraiseUpAPIKeyCredential;
    expect(credential.required).toEqual(expect.arrayContaining(['api_key', 'livemode', 'account_id']));
    expect(credential.properties.livemode).not.toHaveProperty('default');
    expect(credential.properties.api_key['ui:widget']).toBe('password');
    expect(credential).not.toHaveProperty('x-oauth-provider');
  });
  it('discovers an API key method', () => {
    const methods = requirementsFromSchema(schema).map(req => methodFromRequirement(req));
    expect(methods).toHaveLength(1);
    expect(methods[0].credential_type).toBe('fundraise_up_api_key');
    expect(methods[0].method_kind).toBe('api_key');
    expect(methods[0].is_oauth).toBe(false);
  });
  it('selects an owned native row without selecting foreign or shared rows', () => {
    upsertCredentialsIntoCache([{ id: 'owned-key', credential_type: 'fundraise_up_api_key', name: 'Scoped test key', owned_by_me: true },
      { id: 'shared-key', credential_type: 'fundraise_up_api_key', name: 'Shared key', owned_by_me: false },
      { id: 'other-key', credential_type: 'real_geeks_content_token', name: 'Other provider', owned_by_me: true }]);
    expect(autoSelectCredentialFromCache(FundraiseUpNode.type)).toEqual({ fundraise_up_api_key: 'owned-key' });
  });
  it('preserves partial designation fields, labels and saved attachment', () => {
    const created = createWorkflowNode('owned-node', FundraiseUpNode.type, { x: 0, y: 0 }, { operation: 'update_designation', designation_id: 'E1234567', clear_code: true });
    const updated = applyNodeUpdate(created, { credentialIds: { fundraise_up_api_key: 'owned-key' }, config: { designation_id__label: 'Owned fixture' } });
    const saved = buildSaveConfig(updated);
    expect(saved.operation).toBe('update_designation');
    expect(saved.designation_id).toBe('E1234567');
    expect(saved.clear_code).toBe(true);
    expect(saved.designation_id__label).toBe('Owned fixture');
    expect(saved.credentialIds).toEqual({ fundraise_up_api_key: 'owned-key' });
    expect(saved).not.toHaveProperty('livemode');
    expect(updated.data).not.toHaveProperty('designation_id');
  });
  it('keeps the official mark bytes its provenance records', () => {
    const sha = createHash('sha256').update(readFileSync(resolve(process.cwd(), 'public/icons/fundraise-up-brand-vector.svg'))).digest('hex');
    const provenance = JSON.parse(readFileSync(resolve(process.cwd(), 'public/icons/fundraise-up-brand-vector.svg.provenance.json'), 'utf8'));
    expect(sha).toBe('4879348a1208d083e2778489fddf24edb2eb7684d023ea56524f44f01c49228b');
    expect(provenance.sha256).toBe(sha);
  });
});
