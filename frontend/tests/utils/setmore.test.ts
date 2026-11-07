// Setmore self-registration, schema and credential selection regressions.
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));

import { SetmoreNode } from '~/components/workflow/nodes/integrations/setmore';
import { NODE_SCHEMAS, loadNodeSchemas, getAgentToolOperations, getNodeCredentialInfo, filterConfigForExecution, isAgentToolProviderType, isTriggerSource } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { invalidateCredentialsCache, removeCredentialsFromCache, setActiveCredentialWorkflow, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';

import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';

const type = 'automation-setmore';
beforeAll(async () => { await loadNodeSchemas([type]); });
const operations = ['list_services', 'list_categories', 'list_category_services', 'list_staff', 'get_slots', 'find_customers', 'create_customer', 'list_appointments', 'create_appointment', 'update_appointment_label'];

describe('native Setmore source and generated schema', () => {
  it('exposes the manual permanent token and exact scheduling operation set', () => {
    expect(SetmoreNode.type).toBe(type);
    expect(SetmoreNode.label).toBe('Setmore');
    expect(CREDENTIAL_TYPE_MAP.SetmoreRefreshTokenCredential).toBe('setmore_refresh_token');
    expect(getNodeCredentialInfo(type)).toEqual({ providerKey: 'setmore', acceptedTypes: ['setmore_refresh_token'], label: 'Setmore Account' });
    expect(humanizeCredentialLabel('SetmoreRefreshToken')).toBe('Setmore Refresh Token');
    expect(getAgentToolOperations(type).map(op => op.operation).sort()).toEqual([...operations].sort());
    expect(isAgentToolProviderType(type)).toBe(true);
    for (const op of operations) expect(isTriggerSource(type, op)).toBe(false);
    const credential = NODE_SCHEMAS[type].$defs.SetmoreRefreshTokenCredential;
    expect(credential.properties.refresh_token['ui:widget']).toBe('password');
    expect(credential.properties.access_token).toBeUndefined();
    expect(credential['x-credential-type']).toBeUndefined();
    expect(credential['x-oauth-provider']).toBeUndefined();
  });

  it('filters obsolete writes when switching and keeps explicit booking confirmation', () => {
    expect(filterConfigForExecution(type, { operation: 'list_services', item_limit: 5, customer_key: 'customer_42', start_time: '2026-10-07T09:00Z', confirm_booking: true })).toEqual({ operation: 'list_services', item_limit: 5 });
    const defs = Object.values<any>(NODE_SCHEMAS[type].$defs);
    const booking = defs.find(def => def.properties?.operation?.const === 'create_appointment');
    expect(booking.required).toContain('confirm_booking');
    expect(booking.properties.notification).toBeUndefined();
    const listing = defs.find(def => def.properties?.operation?.const === 'list_appointments');
    expect(listing.properties.customerDetails).toBeUndefined();
    expect(listing.properties.cursor).toBeDefined();
  });

  it('uses the unchanged official vector and actual registration/selection entries', () => {
    const tree = join(__dirname, '../..');
    expect(readFileSync(join(tree, 'public/icons/setmore.svg'), 'utf8')).toContain('viewBox="0 0 144 24"');
    expect(readFileSync(join(tree, 'app/schemas/nodeMeta/setmore.json'), 'utf8')).toContain(type);
    expect(readFileSync(join(tree, 'app/schemas/nodeMeta/setmore.json'), 'utf8')).toContain('"autoSelectCredential": true');
  });
});

describe('real Setmore credential cache selection', () => {
  beforeEach(() => {
    removeCredentialsFromCache(['native', 'foreign', 'owner-only']);
    invalidateCredentialsCache();
    setActiveCredentialWorkflow('fixture-workflow');
  });
  it('selects only the owned permanent-token family', () => {
    upsertCredentialsIntoCache([{ id: 'foreign', credential_type: 'setmore_oauth', name: 'Foreign', owned_by_me: true }, { id: 'owner-only', credential_type: 'setmore_refresh_token', name: 'Owner descriptor', owned_by_me: false }]);
    expect(autoSelectCredentialFromCache(type)).toEqual({});
    upsertCredentialsIntoCache([{ id: 'native', credential_type: 'setmore_refresh_token', name: 'Native', owned_by_me: true }]);
    expect(autoSelectCredentialFromCache(type)).toEqual({ setmore_refresh_token: 'native' });
  });
});
