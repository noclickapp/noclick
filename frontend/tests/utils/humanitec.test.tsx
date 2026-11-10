// @vitest-environment jsdom
// Actual native UI/reader/selection fixture source; execution ungranted.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { HumanitecIcon, HumanitecNode } from '~/components/workflow/nodes/integrations/humanitec';
import { getNodeMetadata } from '~/components/workflow/nodes/nodeRegistry';
import schema from '~/schemas/nodes/humanitec.json';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { kindFromCredentialType } from '~/lib/credentialMethodKind';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
const io = vi.hoisted(() => ({ send: vi.fn(), get: vi.fn().mockResolvedValue(null), set: vi.fn(), delete: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: io.send }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: io.get, set: io.set, delete: io.delete } }));
const NODE = 'automation-humanitec', TYPE = 'humanitec_service_token';
afterEach(() => { vi.clearAllMocks(); });
describe('Humanitec native wiring', () => {
    beforeAll(() => loadNodeSchemas([NODE]));
    it('registers and mounts the exact official mark with the actual supplied canvas style', async () => {
        expect(getNodeMetadata(NODE)?.label).toBe('Humanitec'); expect(HumanitecNode.type).toBe(NODE);
        const host = document.createElement('div'), root = createRoot(host);
        const filter = 'drop-shadow(0 1px 2px black)';
        await act(async () => { root.render(<HumanitecIcon style={{ width: 48, height: 48, filter }} />); });
        const image = host.querySelector('img')!;
        expect(image.getAttribute('src')).toBe('/icons/humanitec.svg'); expect(image.style.objectFit).toBe('contain'); expect(image.style.filter).toBe(filter);
        await act(async () => { root.unmount(); });
    });
    it('uses the real nullable credential reader and service-user family without invented OAuth', () => {
        expect(getNodeCredentialInfo(NODE)?.acceptedTypes).toEqual([TYPE]);
        const credential = (schema as any).$defs.HumanitecServiceTokenCredential;
        expect(credential.required).toEqual(expect.arrayContaining(['service_token', 'organization_id']));
        expect(credential.properties.service_token['ui:widget']).toBe('password'); expect(credential.properties.allow_metadata_writes.default).toBe(false);
        expect(kindFromCredentialType(credential['x-credential-type'])).toBe('api_key');
        expect(credential['x-oauth-provider']).toBeUndefined(); expect(credential.properties.refresh_token).toBeUndefined();
        expect((schema as any).properties.credentials.anyOf.some((entry: any) => entry.type === 'null')).toBe(true);
    });
    it('exposes sixteen typed parent-scoped actions without deploy/run/secret/security mutations', () => {
        const operations = getAgentToolOperations(NODE); expect(operations).toHaveLength(16);
        expect(operations.find(value => value.operation === 'get_environment')?.scopableFields).toContainEqual(expect.objectContaining({ field: 'environment_id', loaderField: 'environment_id' }));
        expect(operations.some(value => /^(deploy|run|provision|delete|invite|put_secret|update_pipeline)/.test(value.operation))).toBe(false);
        expect(humanizeCredentialLabel('Humanitec Service User Token')).toBe('Humanitec Service User Token');
    });
    it('uses actual cold/cache selection, prefers healthy own credentials and preserves current dead-key fallback', async () => {
        const cache = await import('~/utils/credentialAutoSelect');
        const select = await import('~/utils/credentialAutoSelectForNode'); cache.invalidateCredentialsCache();
        io.send.mockResolvedValue({ credentials: [{ id: 'foreign', credential_type: 'bearer_token' }, { id: 'null', credential_type: null }, { id: 'revoked', credential_type: TYPE, revoked_at: '2026-01-01' }, { id: 'native', credential_type: TYPE }] });
        expect(await select.autoSelectCredential(NODE)).toEqual({ [TYPE]: 'native' });
        expect(select.autoSelectCredentialFromCache(NODE)).toEqual({ [TYPE]: 'native' }); expect(io.send).toHaveBeenCalledOnce();
        cache.removeCredentialsFromCache(['native']); expect(select.autoSelectCredentialFromCache(NODE)).toEqual({ [TYPE]: 'revoked' });
        cache.removeCredentialsFromCache(['revoked']); cache.upsertCredentialsIntoCache([{ id: 'descriptor', name: 'Shared Humanitec', credential_type: TYPE, owned_by_me: false }]);
        expect(select.autoSelectCredentialFromCache(NODE)).toEqual({}); cache.invalidateCredentialsCache();
    });
});
