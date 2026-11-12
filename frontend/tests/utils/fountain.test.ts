// Exercises Fountain's native generated schema, saved Canvas fields and actual
// credential selector. Storage/socket boundaries are fixtures; no account or
// provider calls are made by this source-only regression packet.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, filterConfigForExecution, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { serializeNodeForSave } from '~/lib/applyNodeUpdate';

const boundary = vi.hoisted(() => ({ send: vi.fn(), get: vi.fn(), set: vi.fn(), delete: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: boundary.send }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: boundary.get, set: boundary.set, delete: boundary.delete } }));
const { invalidateCredentialsCache, removeCredentialsFromCache, upsertCredentialsIntoCache } = await import('~/utils/credentialAutoSelect');
await loadNodeSchemas(['automation-fountain']);
const schema = NODE_SCHEMAS['automation-fountain'];
const { autoSelectCredentialFromCache } = await import('~/utils/credentialAutoSelectForNode');
const ids = ['fountain-owned', 'fountain-shared'];
afterEach(() => { removeCredentialsFromCache(ids); invalidateCredentialsCache(); vi.clearAllMocks(); });

describe('Fountain native wiring', () => {
    it('registers nine operations, private key shape and explicit parent pickers', () => {
        expect(NODE_SCHEMAS['automation-fountain']).toBe(schema);
        const defs: any = schema.$defs;
        expect(Object.keys(schema.properties.config.discriminator.mapping)).toHaveLength(9);
        expect(CREDENTIAL_TYPE_MAP.FountainPrivateHireCredential).toBe('fountain_private_hire');
        expect(defs.FountainPrivateHireCredential.properties.api_key['ui:widget']).toBe('password');
        expect(defs.FountainPrivateHireCredential.properties.tenant.enum).toEqual(['main', 'us-2']);
        expect(defs.GetApplicant.properties.applicant_id['x-dynamic-options'].depends_on).toEqual(['opening_id']);
        expect(Object.keys(defs.ApplicantPatch.properties)).toEqual(['name', 'email', 'phone_number']);
        expect(defs.ApplicantCreate.additionalProperties).toBe(false);
        expect(JSON.stringify(defs.ApplicantCreate)).not.toContain('consent_sms');
        expect(getNodeCredentialInfo('automation-fountain')?.label).toBe('Fountain Account');
    });
    it('preserves actual saved metadata and an explicit false body value', () => {
        const node: any = { id: 'fountain-fixture', type: 'automation-fountain', position: { x: 1, y: 2 }, data: {
            config: { operation: 'create_applicant', opening_id: '00000000-0000-4000-8000-000000000003', body: { name: 'Fixture', email: 'fixture@example.test', phone_number: '+15550000000', check_if_applicant_is_duplicate: false }, stage_id: 'not-selected' },
            label: 'Saved label', _settings: { retryOnFail: 'false' },
        } };
        const saved = serializeNodeForSave(node);
        const filtered: any = filterConfigForExecution(node.type, saved.config);
        expect(filtered.body.check_if_applicant_is_duplicate).toBe(false);
        expect(filtered.operation).toBe('create_applicant');
        expect(filtered.stage_id).toBeUndefined();
        expect(saved.config.label).toBe('Saved label');
    });
    it('selects only an owned Private Hire credential and never an injected shared descriptor', () => {
        invalidateCredentialsCache();
        upsertCredentialsIntoCache([{ id: ids[1], name: 'Shared', credential_type: 'fountain_private_hire', owned_by_me: false }]);
        expect(autoSelectCredentialFromCache('automation-fountain')).toEqual({});
        upsertCredentialsIntoCache([{ id: ids[0], name: 'Owned', credential_type: 'fountain_private_hire', owned_by_me: true }]);
        expect(autoSelectCredentialFromCache('automation-fountain')).toEqual({ fountain_private_hire: ids[0] });
        expect(boundary.send).not.toHaveBeenCalled();
    });
});
