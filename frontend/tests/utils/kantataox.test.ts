// Pin the generated Kantata connection method and trigger metadata.
// Personal bearer tokens must remain hand-connectable without an OAuth popup.
import { describe, expect, it, vi } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/kantataox.json';
import meta from '~/schemas/nodeMeta/kantataox.json';

vi.mock('~/components/workflow/nodes/nodeRegistry', () => ({
    AVAILABLE_NODES: [], getNodeMetadata: () => undefined,
}));
import { KantataOXNode } from '~/components/workflow/nodes/integrations/kantataox';

describe('Kantata OX integration', () => {
    it('offers one manually pasted token method', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(r => r.credential_type)).toEqual(['kantataox_api_token']);
        expect(methodFromRequirement(requirements[0])).toMatchObject({ method_kind: 'api_key', is_oauth: false });
        expect(schema.$defs.KantataOXTokenCredential.required).toEqual(['api_token']);
        expect(schema.$defs.KantataOXTokenCredential.properties.credential_type.default).toBe('kantataox_api_token');
        expect(meta.credentialTypes['Kantata OX Personal Token']).toBe('kantataox_api_token');
        expect(meta.autoSelectCredential).toBe(true);
    });
    it('discovers the definition and all four scheduled triggers', () => {
        expect(KantataOXNode.type).toBe('automation-kantataox');
        expect(KantataOXNode.category).toBe('productivity');
        expect(meta.nodeMeta.triggerOperations).toEqual([
            'on_new_or_updated_project', 'on_new_or_updated_task',
            'on_new_or_updated_time_entry', 'on_new_or_updated_post',
        ]);
    });
});
