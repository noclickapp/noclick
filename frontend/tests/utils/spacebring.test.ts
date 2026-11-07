// Spacebring self-registration, credential selection, typed actions and saves.
import { beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { sendEventAsync } from '~/lib/socket-sender';
import { NODE_SCHEMAS, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { prefetchCredentials, invalidateCredentialsCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { NODE_DEFINITION_FILES } from '~/components/workflow/nodes/nodeDefinitions';
import { isTriggerSource } from '~/utils/nodeMeta';
import { createWorkflowNode, buildSaveConfig } from '~/lib/applyNodeUpdate';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';

describe('native Spacebring customer metadata', () => {
    beforeEach(async () => {
        invalidateCredentialsCache();
        vi.mocked(sendEventAsync).mockResolvedValue({ credentials: [
            { id: 'customer', name: 'Owned Test Network', credential_type: 'spacebring_basic', owned_by_me: true, updated_at: '2026-01-01' },
            { id: 'other', name: 'Different family', credential_type: 'cobot_access_token', updated_at: '2026-02-01' },
        ] });
        await prefetchCredentials();
        await loadNodeSchemas(['automation-spacebring']);
    });
    it('discovers the actual credential class and human title and selects only its family', () => {
        expect(getCredentialTypeFromSchemaTitle('SpacebringBasicCredential')).toBe('spacebring_basic');
        expect(getCredentialTypeFromSchemaTitle('Spacebring Customer Basic Auth')).toBe('spacebring_basic');
        expect(humanizeCredentialLabel('Spacebring Customer Basic Auth')).toBe('Spacebring Customer Basic Auth');
        expect(getNodeCredentialInfo('automation-spacebring')?.acceptedTypes).toEqual(['spacebring_basic']);
        expect(autoSelectCredentialFromCache('automation-spacebring')).toEqual({ spacebring_basic: 'customer' });
        expect(readFileSync('tests/utils/__snapshots__/credentials/spacebring/spacebring_basic.labels.snap.txt', 'utf8')).toContain('Spacebring Customer Basic Auth -> Spacebring Customer Basic Auth');
    });
    it('exposes twelve documented typed actions and credential-bound parents', () => {
        const schema = NODE_SCHEMAS['automation-spacebring'];
        const ops = schema.properties.config.oneOf.map((ref: { $ref: string }) => schema.$defs[ref.$ref.split('/').pop()!].properties.operation.const);
        expect(ops.sort()).toEqual(['check_resource_availability', 'get_booking', 'get_location', 'get_membership', 'get_network', 'get_resource',
            'list_bookings', 'list_locations', 'list_memberships', 'list_resources', 'update_booking_metadata', 'update_resource_metadata']);
        const credential = schema.$defs.SpacebringBasicCredential;
        expect(credential.properties.client_id['ui:widget']).toBe('password');
        expect(credential.properties.client_secret['ui:widget']).toBe('password');
        expect(credential.properties).toHaveProperty('network_id');
        expect(credential.properties).not.toHaveProperty('token_url');
        expect(schema.$defs.GetResource.properties.resource_id['x-dynamic-options'].depends_on).toEqual(['location_id']);
        expect(schema.$defs.GetBooking.properties.booking_id['x-dynamic-options'].depends_on).toEqual(['location_id', 'resource_id']);
        expect(schema.$defs.UpdateBookingMetadata.properties).not.toHaveProperty('paymentMethod');
        expect(schema.$defs.UpdateBookingMetadata.properties).not.toHaveProperty('sendUpdates');
        expect(isTriggerSource('automation-spacebring', 'check_resource_availability')).toBe(false);
        expect(NODE_DEFINITION_FILES).toContainEqual(['automation-spacebring', 'integrations/spacebring']);
        expect(readFileSync('app/components/workflow/nodes/integrations/spacebring.tsx', 'utf8')).toContain("label: 'Spacebring'");
    });
    it('preserves nested parent configuration, saved selection and exact publisher SVG', () => {
        const location = '00000000-0000-4000-8000-000000000004';
        const node = createWorkflowNode('fixture', 'automation-spacebring', { x: 0, y: 0 },
            { operation: 'list_resources', location_id: location, limit: 5 }, { credentialIds: { spacebring_basic: 'customer' } });
        expect(node.data.config).toMatchObject({ location_id: location });
        expect(buildSaveConfig(node).limit).toBe(5);
        expect(buildSaveConfig(node).credentialIds).toEqual({ spacebring_basic: 'customer' });
        const svg = readFileSync('public/icons/spacebring.svg');
        expect(createHash('sha256').update(svg).digest('hex')).toBe('e8a8e60c59961fa6aa4a606813839bfd63ca97f7c18b698490a32020032ad3d0');
        expect(svg.toString()).toContain('width="178" height="50"');
        expect(svg.toString()).not.toMatch(/<script|<foreignObject|onload=|<image/i);
    });
});
