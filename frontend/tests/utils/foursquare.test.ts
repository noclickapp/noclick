import { describe, expect, it, vi } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/foursquare.json';
import meta from '~/schemas/nodeMeta/foursquare.json';

vi.mock('~/components/workflow/nodes/nodeRegistry', () => ({
    AVAILABLE_NODES: [], getNodeMetadata: () => undefined,
}));

import { FoursquareNode } from '~/components/workflow/nodes/integrations/foursquare';

describe('Foursquare connection and catalog', () => {
    it('offers a manually pasted service key as an API key method', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['foursquare_service_key']);
        expect(methodFromRequirement(requirements[0])).toMatchObject({ method_kind: 'api_key', is_oauth: false });
        expect(schema.$defs.FoursquareServiceKey.required).toEqual(['api_key']);
        expect(schema.$defs.FoursquareServiceKey.properties.credential_type.default).toBe('foursquare_service_key');
        expect(meta.credentialTypes['Foursquare Service API Key']).toBe('foursquare_service_key');
        expect(meta.autoSelectCredential).toBe(true);
    });

    it('discovers the definition in the content and research category', () => {
        expect(FoursquareNode.type).toBe('automation-foursquare');
        expect(FoursquareNode.label).toBe('Foursquare');
        expect(FoursquareNode.category).toBe('content-research');
    });
});
