import { beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import schema from '~/schemas/nodes/everflow.json';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution, isAgentToolProviderType } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { invalidateCredentialsCache, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';

describe('Everflow native consumers', () => {
  beforeEach(async () => { invalidateCredentialsCache(); await loadNodeSchemas(['automation-everflow']); });
  it('all three portals keep distinct canonical form choices', () => {
    const info = getNodeCredentialInfo('automation-everflow');
    expect(info?.acceptedTypes).toEqual(['everflow_network_api_key', 'everflow_affiliate_api_key', 'everflow_advertiser_api_key']);
    expect(info?.label).toBe('Everflow');
    for (const portal of ['Network', 'Affiliate', 'Advertiser']) {
      expect(getCredentialTypeFromSchemaTitle(`Everflow ${portal} API Key`)).toBe(`everflow_${portal.toLowerCase()}_api_key`);
    }
  });
  it('real cached selection chooses an owned Network key and excludes injected foreign keys', () => {
    upsertCredentialsIntoCache([
      { id: 'foreign', name: 'Foreign', credential_type: 'everflow_network_api_key', owned_by_me: false },
      { id: 'affiliate', name: 'Affiliate', credential_type: 'everflow_affiliate_api_key', owned_by_me: true },
      { id: 'owned', name: 'Owned', credential_type: 'everflow_network_api_key', owned_by_me: true },
    ]);
    expect(autoSelectCredentialFromCache('automation-everflow')).toEqual({ everflow_network_api_key: 'owned' });
  });
  it('actual operation filtering drops stale channel write values from reads', () => {
    expect(filterConfigForExecution('automation-everflow', { operation: 'get_offer', offer_id: '7', channel_id: '9', name: 'stale', expected_name: 'stale' })).toEqual({ operation: 'get_offer', offer_id: '7' });
    expect(getAgentToolOperations('automation-everflow')).toHaveLength(21);
    expect(isAgentToolProviderType('automation-everflow')).toBe(true);
  });
  it('typed source exposes no arbitrary API or financial operation and retains official SVG bytes', () => {
    const operations = getAgentToolOperations('automation-everflow').map(op => op.operation);
    expect(operations).toContain('get_report_summary');
    expect(operations).toContain('delete_channel');
    expect(operations.some(op => /conversion|payout|tracking_link|payment|export/.test(op))).toBe(false);
    expect(schema['x-agent-tool-provider']).toBe(true);
    const svg = readFileSync(join(__dirname, '../../public/icons/everflow.svg'), 'utf8');
    expect(svg).toContain('viewBox="-0.628 -0.726 37.766 35.453"');
    expect(svg.match(/<path /g)).toHaveLength(3);
    expect(svg).not.toMatch(/<script|<image|href=/);
  });
});
