// NationBuilder self-registration, generated credentials and cache selection.
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));

import { NationBuilderNode } from '~/components/workflow/nodes/integrations/nationbuilder';
import { NODE_SCHEMAS, loadNodeSchemas, getAgentToolOperations, getNodeCredentialInfo, filterConfigForExecution, isAgentToolProviderType, isTriggerSource } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { invalidateCredentialsCache, removeCredentialsFromCache, setActiveCredentialWorkflow, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';

import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';

const type = 'automation-nationbuilder';
beforeAll(async () => { await loadNodeSchemas([type]); });
const operations = ['get_me', 'list_signups', 'get_signup', 'create_signup', 'update_signup', 'list_tags', 'get_tag', 'create_tag', 'update_tag', 'delete_tag', 'list_lists', 'get_list', 'create_list', 'update_list', 'delete_list', 'list_list_signups', 'list_signup_taggings', 'tag_signup', 'untag_signup', 'add_list_signups', 'remove_list_signups', 'get_async_process'];

describe('native NationBuilder source and generated schema', () => {
  it('requires the nation-bound supplied v2 token without a global OAuth client', () => {
    expect(NationBuilderNode.type).toBe(type);
    expect(NationBuilderNode.label).toBe('NationBuilder');
    expect(CREDENTIAL_TYPE_MAP.NationBuilderV2TokenCredential).toBe('nationbuilder_v2_token');
    expect(getNodeCredentialInfo(type)).toEqual({ providerKey: 'nationbuilder', acceptedTypes: ['nationbuilder_v2_token'], label: 'NationBuilder V2 Token' });
    expect(getAgentToolOperations(type).map(op => op.operation).sort()).toEqual([...operations].sort());
    expect(isAgentToolProviderType(type)).toBe(true);
    for (const op of operations) expect(isTriggerSource(type, op)).toBe(false);
    const credential = NODE_SCHEMAS[type].$defs.NationBuilderV2TokenCredential;
    expect(credential.properties.access_token['ui:widget']).toBe('password');
    expect(credential.required).toEqual(expect.arrayContaining(['nation_slug', 'access_token']));
    expect(credential.properties.refresh_token).toBeUndefined();
    expect(credential['x-oauth-provider']).toBeUndefined();
    expect(credential['x-credential-type']).toBeUndefined();
  });

  it('switching operations filters obsolete write fields and preserves scoped parents', () => {
    expect(filterConfigForExecution(type, { operation: 'list_lists', page_size: 5, name: 'Old write', signup_id: '1', email: 'private@example.invalid' })).toEqual({ operation: 'list_lists', page_size: 5 });
    const defs = Object.values<any>(NODE_SCHEMAS[type].$defs);
    const tagging = defs.find(def => def.properties?.operation?.const === 'untag_signup');
    expect(tagging.required).toEqual(expect.arrayContaining(['signup_id', 'tag_id', 'tagging_id']));
    expect(tagging.properties.tagging_id['x-dynamic-options'].depends_on).toEqual(['signup_id', 'tag_id']);
    const creation = defs.find(def => def.properties?.operation?.const === 'create_signup');
    expect(creation.properties.email_opt_in).toBeUndefined();
    expect(creation.properties.custom_values).toBeUndefined();
    expect(operations).not.toContain('delete_signup');
    expect(operations).not.toContain('send_message');
  });

  it('keeps the official mark and actual registration and selection entries', () => {
    const tree = join(__dirname, '../..');
    expect(readFileSync(join(tree, 'public/icons/nationbuilder.svg'), 'utf8')).toContain('viewBox="0 0 1000 1000"');
    expect(readFileSync(join(tree, 'app/components/workflow/nodes/integrations/nationbuilder.tsx'), 'utf8')).toContain("type: 'automation-nationbuilder'");
    expect(JSON.parse(readFileSync(join(tree, 'app/schemas/nodeMeta/nationbuilder.json'), 'utf8')).providerLabels.nationbuilder).toBe('NationBuilder V2 Token');
  });
});

describe('real NationBuilder credential cache selection', () => {
  beforeEach(() => {
    removeCredentialsFromCache(['native-nb', 'foreign-nb', 'owner-nb']);
    invalidateCredentialsCache();
    setActiveCredentialWorkflow('fixture-workflow');
  });
  it('selects only an owned native v2 credential', () => {
    upsertCredentialsIntoCache([{ id: 'foreign-nb', credential_type: 'nationbuilder_v1_token', name: 'Foreign', owned_by_me: true }, { id: 'owner-nb', credential_type: 'nationbuilder_v2_token', name: 'Owner descriptor', owned_by_me: false }]);
    expect(autoSelectCredentialFromCache(type)).toEqual({});
    upsertCredentialsIntoCache([{ id: 'native-nb', credential_type: 'nationbuilder_v2_token', name: 'Native', owned_by_me: true }]);
    expect(autoSelectCredentialFromCache(type)).toEqual({ nationbuilder_v2_token: 'native-nb' });
  });
});
