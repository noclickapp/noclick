// Schema, credential selection and save regressions for the Bókun integration.
// These consume its generated schema and discovered node definition on staging.
import { beforeEach, describe, expect, it, vi } from 'vitest';
// The catalog imports agent/MCP icons too; this regression never renders those components.
vi.mock('@lobehub/icons', () => {
    const Icon = Object.assign(() => null, { Avatar: () => null, Color: () => null });
    return new Proxy({}, { has: () => true, get: (_target, key) => key === 'then' ? undefined : Icon });
});
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { sendEventAsync } from '~/lib/socket-sender';
import { NODE_SCHEMAS, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { prefetchCredentials, invalidateCredentialsCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { AVAILABLE_NODES } from '~/components/workflow/nodes/nodeRegistry';
import { isTriggerSource } from '~/utils/nodeMeta';
import { createWorkflowNode, buildSaveConfig } from '~/lib/applyNodeUpdate';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

describe('Bókun native management node', () => {
    beforeEach(async () => {
        await loadNodeSchemas(['automation-bokun']);
        invalidateCredentialsCache();
        vi.mocked(sendEventAsync).mockResolvedValue({ credentials: [
            { id: 'owned-hmac', name: 'Owned REST', credential_type: 'bokun_rest_hmac', updated_at: '2026-01-01' },
            { id: 'owned-app', name: 'Owned App', credential_type: 'bokun_app_token', updated_at: '2026-01-01' },
            { id: 'foreign', name: 'Other service', credential_type: 'other_api_key', updated_at: '2026-02-01' },
        ] });
        await prefetchCredentials();
    });
    it('discovers all three distinct manual families', () => {
        expect(getCredentialTypeFromSchemaTitle('BokunRESTHMACCredential')).toBe('bokun_rest_hmac');
        expect(getCredentialTypeFromSchemaTitle('Bókun REST Key Pair')).toBe('bokun_rest_keys');
        expect(getCredentialTypeFromSchemaTitle('Bókun Existing App Token')).toBe('bokun_app_token');
        expect(getNodeCredentialInfo('automation-bokun')?.acceptedTypes).toEqual(expect.arrayContaining(['bokun_rest_hmac', 'bokun_rest_keys', 'bokun_app_token']));
        // Staging selects the primary credential family; the other methods stay selectable in the form.
        expect(autoSelectCredentialFromCache('automation-bokun')).toEqual({ bokun_rest_hmac: 'owned-hmac' });
    });
    it('exposes exact operations, family badges and real fields', () => {
        const schema = NODE_SCHEMAS['automation-bokun'];
        const operations = schema.properties.config.oneOf.map((ref: { $ref: string }) => schema.$defs[ref.$ref.split('/').pop()!].properties.operation.const);
        expect(operations).toHaveLength(19);
        expect(operations).toContain('update_experience_metadata');
        expect(operations).toContain('delete_unused_pricing_category');
        expect(operations).not.toContain('create_booking');
        expect(operations).not.toContain('refund');
        expect(schema.$defs.BokunRESTHMACCredential.properties.secret_key['ui:widget']).toBe('password');
        expect(schema.$defs.BokunAppTokenCredential.properties.access_token['ui:widget']).toBe('password');
        expect(schema.$defs.BokunAppTokenCredential.properties).not.toHaveProperty('origin');
        expect(schema.$defs.GetGraphQLBooking['x-tier-label']).toBe('Existing App Token');
        expect(schema.$defs.UpdateExperienceMetadata.properties.short_description['ui:widget']).toBe('textarea');
        expect(schema.$defs.GetActivityAvailability.required).toEqual(expect.arrayContaining(['activity_id', 'currency', 'start', 'end']));
        expect(isTriggerSource('automation-bokun', 'get_booking_status')).toBe(false);
        expect(AVAILABLE_NODES.find(n => n.type === 'automation-bokun')?.label).toBe('Bókun');
    });
    it('preserves native nested saves and exact private icon packaging', () => {
        const node = createWorkflowNode('fixture', 'automation-bokun', { x: 0, y: 0 },
            { operation: 'list_pricing_categories', page_no: 2, page_size: 25 },
            { credentialIds: { bokun_rest_hmac: 'owned-hmac' } });
        expect(node.data.config).toMatchObject({ page_no: 2 });
        expect(buildSaveConfig(node).page_size).toBe(25);
        expect(buildSaveConfig(node).credentialIds).toEqual({ bokun_rest_hmac: 'owned-hmac' });
        const svg = readFileSync(resolve('public/icons/bokun-native-brand-20261012.svg'), 'utf8');
        expect(svg).toContain('<svg');
        expect(svg).not.toMatch(/<script|<foreignObject|onload=|href=["']https?:/i);
    });
});
