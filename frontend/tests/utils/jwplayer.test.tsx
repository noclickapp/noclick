// Native JWX palette, credential, operation and logo checks. No provider calls.
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { JWPlayerNode } from '~/components/workflow/nodes/integrations/jwplayer';
import { NODE_DEFINITION_FILES } from '~/components/workflow/nodes/nodeDefinitions';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { filterConfigForExecution, getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { removeCredentialsFromCache, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import fixture from '../fixtures/jwplayer-native.json';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));

describe('JWX native property metadata', () => {
    beforeAll(() => loadNodeSchemas([fixture.type]));
    it('is discoverable in the registry used by both native palettes', () => {
        expect(NODE_DEFINITION_FILES.some(([type, module]) => type === fixture.type && module === 'integrations/jwplayer')).toBe(true);
        expect(JWPlayerNode.label).toBe('JWX (JW Player)');
        expect(JWPlayerNode.keywords).toContain('jwp');
    });
    it('resolves nullable credentials and exact class/title database families', () => {
        expect(CREDENTIAL_TYPE_MAP.JWPlayerAPISecretCredential).toBe(fixture.credentialFamily);
        expect(CREDENTIAL_TYPE_MAP[fixture.credentialTitle]).toBe(fixture.credentialFamily);
        expect(getNodeCredentialInfo(fixture.type)?.acceptedTypes).toEqual([fixture.credentialFamily]);
    });
    it('exposes only five reads and filters known fields from other operations', () => {
        expect(getAgentToolOperations(fixture.type).map(op => op.operation).sort()).toEqual([...fixture.operations].sort());
        const data = filterConfigForExecution(fixture.type, { ...fixture.data.config, page: 2, page_length: 8, playlist_id: 'abc123XY', harmlessSidecar: 'kept' });
        expect(data.media_id).toBe('Ny05CEfj');
        expect(data).not.toHaveProperty('page');
        expect(data).not.toHaveProperty('page_length');
        expect(data).not.toHaveProperty('playlist_id');
        expect(data.harmlessSidecar).toBe('kept');
        expect(JSON.stringify(fixture)).not.toContain('"api_secret":');
    });
    it('preserves the current official PNG bytes and contained-image surface', () => {
        const icon = readFileSync(new URL('../../public/icons/jwplayer.png', import.meta.url));
        expect(createHash('sha256').update(icon).digest('hex')).toBe(fixture.icon.sha256);
        expect(icon.readUInt32BE(16)).toBe(fixture.icon.width);
        expect(icon.readUInt32BE(20)).toBe(fixture.icon.height);
        const render = (JWPlayerNode.Icon as any).render({ style: { width: 48 } }, null);
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
