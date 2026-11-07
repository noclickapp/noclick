import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { join } from 'node:path';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution, isAgentToolProviderType } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { invalidateCredentialsCache, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/staffbase.json';

describe('Staffbase native consumers', () => {
  beforeAll(() => loadNodeSchemas(['automation-staffbase']));
  beforeEach(() => invalidateCredentialsCache());
  it('discovers the exact tenant key credential and both title maps', () => {
    expect(getNodeCredentialInfo('automation-staffbase')?.acceptedTypes).toEqual(['staffbase_api_token']);
    expect(getNodeCredentialInfo('automation-staffbase')?.label).toBe('Staffbase Prepared API Token');
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    expect(getCredentialTypeFromSchemaTitle('StaffbaseApiTokenCredential')).toBe('staffbase_api_token');
    expect(getCredentialTypeFromSchemaTitle('Staffbase Prepared API Token')).toBe('staffbase_api_token');
  });
  it('actual cached selection excludes foreign and display-only rows', () => {
    upsertCredentialsIntoCache([
      { id: 'foreign', name: 'Foreign', credential_type: 'donorbox_organization_api_key', owned_by_me: true },
      { id: 'display', name: 'Display', credential_type: 'staffbase_api_token', owned_by_me: false },
      { id: 'owned', name: 'Owned', credential_type: 'staffbase_api_token', owned_by_me: true },
    ]);
    expect(autoSelectCredentialFromCache('automation-staffbase')).toEqual({ staffbase_api_token: 'owned' });
  });
  it('exposes 23 native operations and removes fields from other operations', () => {
    expect(filterConfigForExecution('automation-staffbase', { operation: 'update_draft_post', channel_id: 'c1', post_id: 'n1', title: 'Changed', user_id: 'u1' })).toEqual({ operation: 'update_draft_post', channel_id: 'c1', post_id: 'n1', title: 'Changed' });
    const operations = getAgentToolOperations('automation-staffbase').map(op => op.operation);
    expect(operations).toHaveLength(23);
    expect(operations).toContain('list_users');
    expect(operations).toContain('create_draft_page');
    expect(operations.some(op => /publish|permission|membership|send_notification/.test(op))).toBe(false);
    expect(isAgentToolProviderType('automation-staffbase')).toBe(true);
    const post = getAgentToolOperations('automation-staffbase').find(op => op.operation === 'get_post');
    expect(post?.scopableFields).toEqual(expect.arrayContaining([
      expect.objectContaining({ field: 'post_id', dependsOn: 'channel_id' }),
    ]));
    const page = getAgentToolOperations('automation-staffbase').find(op => op.operation === 'get_page');
    expect(page?.scopableFields).toEqual(expect.arrayContaining([
      expect.objectContaining({ field: 'page_id', dependsOn: 'space_id' }),
    ]));
  });
  it('keeps exact official SVG bytes and square icon viewbox', () => {
    const svg = readFileSync(join(__dirname, '../../public/icons/staffbase.svg'));
    expect(svg.length).toBe(796);
    expect(createHash('sha256').update(svg).digest('hex')).toBe('ee3a3f8547422bcf86849b0200a57895efe3ffd785170ea52c770aff8e9bc70e');
    expect(svg.toString()).toContain('viewBox="0 0 400 400"');
    expect(svg.toString()).not.toMatch(/<script|<image|href=/);
  });
});
