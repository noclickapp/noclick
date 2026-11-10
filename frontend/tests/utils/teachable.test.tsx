import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TeachableIcon, TeachableNode } from '~/components/workflow/nodes/integrations/teachable';
import { getNodeMetadata } from '~/components/workflow/nodes/nodeRegistry';
import schema from '~/schemas/nodes/teachable.json';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchema } from '~/utils/credentialTypes';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

// Only socket/cache boundaries are synthetic; schema, readers and selectors stay real.
const io = vi.hoisted(() => ({ send: vi.fn(), get: vi.fn().mockResolvedValue(null), set: vi.fn(), delete: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: io.send }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: io.get, set: io.set, delete: io.delete } }));
const TYPES = ['teachable_api_key', 'teachable_supplied_oauth'];
const NODE = 'automation-teachable';
await loadNodeSchemas([NODE]);
afterEach(() => { vi.clearAllMocks(); });

describe('Teachable native wiring', () => {
    it('registers the native definition and preserves exact official SVG geometry under the supplied canvas filter', async () => {
        expect(getNodeMetadata(NODE)?.label).toBe('Teachable');
        expect(TeachableNode.type).toBe(NODE);
        const markup = renderToStaticMarkup(<TeachableIcon style={{ width: 48, height: 48, filter: 'invert(var(--brand-invert, 0)) drop-shadow(0 1px 2px black)' }} />);
        expect(markup).toContain('src="/icons/teachable.png"');
        expect(markup).toContain('object-fit:contain');
        expect(markup).toContain('invert(var(--brand-invert, 0))');
    });
    it('reads both native nullable models through actual credential readers without converting the supplied grant into login OAuth', () => {
        const info = getNodeCredentialInfo(NODE)!;
        expect(info.acceptedTypes).toEqual(TYPES);
        expect(info.label).toBe('Teachable API');
        const prop: any = schema.properties.credentials;
        expect(prop.anyOf.some((entry: any) => entry.type === 'null')).toBe(true);
        const defs = (schema as any).$defs;
        expect(prop.anyOf.filter((entry: any) => entry.$ref).map((entry: any) => getCredentialTypeFromSchema(defs[entry.$ref.split('/').pop()]))).toEqual(TYPES);
        expect(defs.TeachableSuppliedOAuthCredential.required).toContain('expected_user_id');
        expect(defs.TeachableSuppliedOAuthCredential['x-oauth-provider']).toBeUndefined();
        expect(defs.TeachableAPIKeyCredential.properties.allow_management_writes.default).toBe(false);
    });
    it('offers supplied tokens as fields without advertising an unavailable OAuth connect flow', () => {
        const methods = requirementsFromSchema(schema).map(methodFromRequirement);
        expect(methods.map(method => method.method_kind)).toEqual(['api_key', 'api_key']);
        expect(methods.every(method => !method.is_oauth)).toBe(true);
    });
    it('enumerates the twenty closed actions and actual lecture-course picker dependency', () => {
        const ops = getAgentToolOperations(NODE);
        expect(ops).toHaveLength(20);
        expect(ops.find(op => op.operation === 'get_lecture_completion')?.scopableFields).toContainEqual(expect.objectContaining({ field: 'lecture_id', loaderField: 'lecture_id', dependsOn: 'course_id' }));
        expect(ops.find(op => op.operation === 'enroll_user')?.category).toBe('Management');
        expect(ops.some(op => /billing|refund|subscription|session|password|role|download|video/.test(op.operation))).toBe(false);
    });
    it('keeps exact native method labels readable through the existing humanizer', () => {
        expect(humanizeCredentialLabel('Teachable Admin API Key')).toBe('Teachable Admin API Key');
        expect(humanizeCredentialLabel('Teachable Supplied User OAuth v2')).toBe('Teachable Supplied User OAuth v2');
    });
    it('uses the real cold/cached auto selector for an actual Admin row, excluding foreign and revoked credentials', async () => {
        const cache = { ...await import('~/utils/credentialAutoSelect'), ...await import('~/utils/credentialAutoSelectForNode') }; cache.invalidateCredentialsCache();
        io.send.mockResolvedValue({ credentials: [
            { id: 'foreign', credential_type: 'foreign_api_key', updated_at: '2026-01-05' },
            { id: 'dead', credential_type: TYPES[0], revoked_at: '2026-01-04', updated_at: '2026-01-04' },
            { id: 'native', credential_type: TYPES[0], updated_at: '2026-01-02' },
            { id: 'oauth-explicit', credential_type: TYPES[1], updated_at: '2026-01-06' },
        ] });
        expect(await cache.autoSelectCredential(NODE)).toEqual({ [TYPES[0]]: 'native' });
        expect(cache.autoSelectCredentialFromCache(NODE)).toEqual({ [TYPES[0]]: 'native' });
        expect(io.send).toHaveBeenCalledOnce();
    });
    it('keeps nullable/foreign/display-only descriptors out of automatic credential selection', async () => {
        const cache = { ...await import('~/utils/credentialAutoSelect'), ...await import('~/utils/credentialAutoSelectForNode') }; cache.invalidateCredentialsCache();
        io.send.mockResolvedValue({ credentials: [{ id: 'nil', credential_type: null }, { id: 'other', credential_type: 'foreign_api_key' }] });
        expect(await cache.autoSelectCredential(NODE)).toEqual({});
        cache.upsertCredentialsIntoCache([{ id: 'descriptor', name: 'Shared Teachable', credential_type: TYPES[0], owned_by_me: false }]);
        expect(cache.autoSelectCredentialFromCache(NODE)).toEqual({});
        cache.removeCredentialsFromCache(['descriptor']); cache.invalidateCredentialsCache();
    });
});
