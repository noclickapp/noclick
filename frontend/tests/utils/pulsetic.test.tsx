// Pulsetic discovery, credential selection and config filtering against the native frontend.
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { PulseticNode } from '~/components/workflow/nodes/integrations/pulsetic';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { filterConfigForExecution, getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { removeCredentialsFromCache, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { NODE_DEFINITION_FILES, getNodeDefinition, loadNodeDefinitions } from '~/components/workflow/nodes/nodeDefinitions';
import fixture from '../fixtures/pulsetic-native.json';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));

beforeAll(async () => {
    await loadNodeSchemas([fixture.type]);
    await loadNodeDefinitions([fixture.type]);
});

describe('Pulsetic native protected metadata', () => {
    it('is discoverable in the registry used by both native palettes', () => {
        expect(NODE_DEFINITION_FILES).toContainEqual([fixture.type, 'integrations/pulsetic']);
        expect(getNodeDefinition(fixture.type)).toBe(PulseticNode);
        expect(PulseticNode.label).toBe('Pulsetic');
        expect(PulseticNode.keywords).toContain('uptime');
    });
    it('resolves nullable credentials and exact class/title database families', () => {
        expect(CREDENTIAL_TYPE_MAP.PulseticAPIKeyCredential).toBe(fixture.credentialFamily);
        expect(CREDENTIAL_TYPE_MAP[fixture.credentialTitle]).toBe(fixture.credentialFamily);
        expect(getNodeCredentialInfo(fixture.type)?.acceptedTypes).toEqual([fixture.credentialFamily]);
    });
    it('exposes only eleven reads and filters known fields from other operations', () => {
        expect(getAgentToolOperations(fixture.type).map(op => op.operation).sort()).toEqual([...fixture.operations].sort());
        const data = filterConfigForExecution(fixture.type, { ...fixture.data.config, page: 2, per_page: 8, heartbeat_id: '5', harmlessSidecar: 'kept' });
        expect(data.monitor_id).toBe('7');
        expect(data).not.toHaveProperty('page');
        expect(data).not.toHaveProperty('per_page');
        expect(data).not.toHaveProperty('heartbeat_id');
        expect(data.harmlessSidecar).toBe('kept');
        expect(JSON.stringify(fixture)).not.toContain('"api_key":');
    });
    it('preserves the current official SVG bytes and contained-image surface', () => {
        const icon = readFileSync(new URL('../../public/icons/pulsetic.svg', import.meta.url));
        expect(createHash('sha256').update(icon).digest('hex')).toBe(fixture.icon.sha256);
        expect(icon.toString()).toContain('viewBox="0 0 400 400"');
        const render = (PulseticNode.Icon as any).render({ style: { width: 48 } }, null);
        expect(render.type).toBe('img');
        expect(render.props.src).toBe(fixture.icon.path);
        expect(render.props.style).toEqual({ objectFit: 'contain', width: 48 });
    });
    it('automatically selects an owned native credential, excluding foreign descriptors', () => {
        const foreign = { id: 'foreign-jwx', name: 'Shared descriptor', credential_type: fixture.credentialFamily };
        const own = { id: 'own-jwx', name: 'Own secret', credential_type: fixture.credentialFamily, owned_by_me: true };
        upsertCredentialsIntoCache([foreign]);
        expect(autoSelectCredentialFromCache(fixture.type)).toEqual({});
        upsertCredentialsIntoCache([own]);
        expect(autoSelectCredentialFromCache(fixture.type)).toEqual({ [fixture.credentialFamily]: own.id });
        removeCredentialsFromCache([foreign.id, own.id]);
    });
});
