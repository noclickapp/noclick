// UNRUN actual native schema/selection/search/projection fixture source.
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import fixture from '../fixtures/aprimo-native.json';
import { AprimoNode } from '~/components/workflow/nodes/integrations/aprimo';
import { AVAILABLE_NODES } from '~/components/workflow/nodes/nodeRegistry';
import { buildNodeSearchIndexEntry, getNodeSearchScore } from '~/utils/nodeSearchMatch';
import { filterNodeServices } from '~/utils/nodeServiceSearch';
import { getAgentToolOperations, getNodeCredentialInfo, filterConfigForExecution, loadNodeSchemas } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { invalidateCredentialsCache, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';

import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { clear: vi.fn(), get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));

describe('Aprimo DAM native surfaces', () => {
    beforeAll(async () => { await loadNodeSchemas([fixture.node_type]); });
    beforeEach(() => invalidateCredentialsCache());
    it('uses actual native registration and both service selectors', () => {
        expect(AVAILABLE_NODES.find(node => node.type === fixture.node_type)?.label).toBe('Aprimo DAM');
        expect(getNodeSearchScore(buildNodeSearchIndexEntry(AprimoNode), 'Aprimo')).not.toBeNull();
        const service = { nodeType: AprimoNode.type, label: AprimoNode.label, keywords: AprimoNode.keywords };
        expect(filterNodeServices([service], 'digital asset management', 'tool')).toHaveLength(1);
        expect(getAgentToolOperations(fixture.node_type).map(op => op.operation).sort()).toEqual([...fixture.operations].sort());
    });
    it('maps native class/title and never auto-selects collaborative display credentials', () => {
        expect(CREDENTIAL_TYPE_MAP.AprimoBearerCredential).toBe(fixture.credential_type);
        expect(CREDENTIAL_TYPE_MAP['Aprimo DAM Bearer Token']).toBe(fixture.credential_type);
        expect(getNodeCredentialInfo(fixture.node_type)?.acceptedTypes).toEqual([fixture.credential_type]);
        upsertCredentialsIntoCache([{ id: 'display', name: 'Display only', credential_type: fixture.credential_type }]);
        expect(autoSelectCredentialFromCache(fixture.node_type)).toEqual({});
        upsertCredentialsIntoCache([{ id: 'own', name: 'Owned Aprimo', credential_type: fixture.credential_type, owned_by_me: true } as any]);
        expect(autoSelectCredentialFromCache(fixture.node_type)).toEqual({ aprimo_bearer: 'own' });
    });
    it('filters fields through the selected operation while retaining metadata', () => {
        const result = filterConfigForExecution(fixture.node_type, { operation: 'get_classification', include_names: false, record_id: 'held-other-operation', sidecar: 'retained' });
        expect(result).toMatchObject({ operation: 'get_classification', include_names: false, sidecar: 'retained' });
        expect(result).not.toHaveProperty('record_id');
        expect(JSON.stringify(fixture)).not.toContain('"access_token":');
    });
    it('retains exact official vendor SVG', () => {
        const bytes = readFileSync(new URL('../../public/icons/aprimo.svg', import.meta.url));
        expect(createHash('sha256').update(bytes).digest('hex')).toBe(fixture.official_icon_sha256);
        expect(bytes.toString()).toContain('viewBox="0 0 180 180"');
    });
});
