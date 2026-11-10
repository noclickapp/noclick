import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { join } from 'node:path';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution, isAgentToolProviderType, loadNodeSchemas } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { invalidateCredentialsCache, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';

import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';

describe('Bloomerang native consumers', () => {
  beforeAll(() => loadNodeSchemas(['automation-bloomerang']));
  beforeEach(() => invalidateCredentialsCache());
  it('uses private CRM keys with the real title mapping', () => {
    expect(getNodeCredentialInfo('automation-bloomerang')?.acceptedTypes).toEqual(['bloomerang_private_api_key']);
    expect(getNodeCredentialInfo('automation-bloomerang')?.label).toBe('Bloomerang');
    expect(getCredentialTypeFromSchemaTitle('BloomerangPrivateApiKeyCredential')).toBe('bloomerang_private_api_key');
    expect(getCredentialTypeFromSchemaTitle('Bloomerang Private CRM API Key')).toBe('bloomerang_private_api_key');
  });
  it('actual selection excludes foreign, public and display-only keys', () => {
    upsertCredentialsIntoCache([
      { id: 'foreign', name: 'Foreign', credential_type: 'slack_bot_token', owned_by_me: true },
      { id: 'public', name: 'Public', credential_type: 'bloomerang_public_key', owned_by_me: true },
      { id: 'shared', name: 'Display only', credential_type: 'bloomerang_private_api_key', owned_by_me: false },
      { id: 'owned', name: 'CRM', credential_type: 'bloomerang_private_api_key', owned_by_me: true },
    ]);
    expect(autoSelectCredentialFromCache('automation-bloomerang')).toEqual({ bloomerang_private_api_key: 'owned' });
  });
  it('filters stale writes from reads and offers twenty-seven typed tools', () => {
    expect(filterConfigForExecution('automation-bloomerang', { operation: 'get_note', constituent_id: '42', note_id: '43', note: 'stale', expected_note: 'stale' })).toEqual({ operation: 'get_note', constituent_id: '42', note_id: '43' });
    const operations = getAgentToolOperations('automation-bloomerang').map(op => op.operation);
    expect(operations).toHaveLength(27);
    expect(operations).toContain('create_household');
    expect(operations).toContain('delete_note');
    expect(operations.some(op => /donation|payment|refund|email|invite|consent|transaction/.test(op))).toBe(false);
    expect(isAgentToolProviderType('automation-bloomerang')).toBe(true);
  });
  it('preserves the exact official wide wordmark', () => {
    const svg = readFileSync(join(__dirname, '../../public/icons/bloomerang.svg'));
    expect(svg.length).toBe(5693);
    expect(createHash('sha256').update(svg).digest('hex')).toBe('d1758235f3bd938e2ffd11a4b9ac91c57e06b8d702a253959c63b3b1a73caf6e');
    expect(svg.toString()).toContain('viewBox="0 0 203 37"');
    expect(svg.toString()).not.toMatch(/<script|<image|href=/);
  });
});
