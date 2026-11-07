// @vitest-environment happy-dom
import { render, cleanup } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest';
import { QwilrNode } from '~/components/workflow/nodes/integrations/qwilr';
import { NODE_SCHEMAS, getNodeCredentialInfo, filterConfigForExecution, loadNodeSchemas } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
const boundary = vi.hoisted(() => ({ send: vi.fn(), get: vi.fn(), set: vi.fn(), delete: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: boundary.send }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: boundary.get, set: boundary.set, delete: boundary.delete } }));
const { invalidateCredentialsCache, upsertCredentialsIntoCache, removeCredentialsFromCache } = await import('~/utils/credentialAutoSelect');

beforeAll(async () => { await loadNodeSchemas(['automation-qwilr']); });

beforeEach(() => { vi.clearAllMocks(); });
afterEach(() => { cleanup(); removeCredentialsFromCache(['synthetic-qwilr-own', 'synthetic-qwilr-other']); invalidateCredentialsCache(); });
it('retains the account-token family, native metadata and deliberate write control', () => {
    const schema: any = NODE_SCHEMAS['automation-qwilr'];
    expect(requirementsFromSchema(schema).map(a => a.credential_type)).toEqual(['qwilr_api_token']);
    expect(CREDENTIAL_TYPE_MAP.QwilrAPITokenCredential).toBe('qwilr_api_token');
    expect(getNodeCredentialInfo('automation-qwilr')?.acceptedTypes).toEqual(['qwilr_api_token']);
    expect(getNodeCredentialInfo('automation-qwilr')?.label).toBe('Qwilr Account Token');
    const write: any = Object.values(schema.$defs).find((d: any) => d.properties?.operation?.const === 'create_draft_from_blocks');
    expect(write.properties.saved_block_id['x-resource-type']).toBe('qwilr_saved_block');
    expect(write.properties.acknowledge_live_account_effects).toMatchObject({ type: 'boolean' });
    expect(write.properties.acknowledge_live_account_effects.const).toBeUndefined();
    expect(schema.$defs.QwilrAPITokenCredential.properties.api_token['ui:sensitive']).toBe(true);
    expect(schema.$defs.QwilrAPITokenCredential['x-oauth-provider']).toBeUndefined();
    expect(requirementsFromSchema(schema).map(req => methodFromRequirement(req).method_kind)).toEqual(['api_key']);
    expect(filterConfigForExecution('automation-qwilr', { operation: 'get_page', page_id: '6ee0f841f3cc8900090d82dc', metadata: { stale: 'value' } })).toEqual({ operation: 'get_page', page_id: '6ee0f841f3cc8900090d82dc' });
});
it('renders the exact checked-in vendor vector used by the node definition', () => {
    const { container } = render(<QwilrNode.Icon />);
    expect(container.querySelector('img')?.getAttribute('src')).toBe('/icons/qwilr.svg');
    expect(QwilrNode.label).toBe('Qwilr');
});
it('selects the current owned family through the real canvas cache selector', () => {
    invalidateCredentialsCache();
    upsertCredentialsIntoCache([{ id: 'synthetic-qwilr-other', name: 'Other owner', credential_type: 'qwilr_api_token', owned_by_me: false }]);
    expect(autoSelectCredentialFromCache('automation-qwilr')).toEqual({});
    upsertCredentialsIntoCache([{ id: 'synthetic-qwilr-own', name: 'Owned Qwilr', credential_type: 'qwilr_api_token', owned_by_me: true }]);
    expect(autoSelectCredentialFromCache('automation-qwilr')).toEqual({ qwilr_api_token: 'synthetic-qwilr-own' });
    expect(boundary.send).not.toHaveBeenCalled(); expect(boundary.get).not.toHaveBeenCalled();
});
