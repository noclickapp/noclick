import { describe, expect, it, vi } from 'vitest';
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/beatapi.json';
import meta from '~/schemas/nodeMeta/beatapi.json';

vi.mock('~/components/workflow/nodes/nodeRegistry', () => ({
    AVAILABLE_NODES: [],
    getNodeMetadata: () => undefined,
}));

import { BeatapiNode } from '~/components/workflow/nodes/integrations/beatapi';

describe('BeatAPI connection catalog', () => {
    it('offers a manually entered API key with the official label', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map((req) => req.credential_type)).toEqual([
            'beatapi_api_key',
        ]);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe(
            'api_key'
        );
        expect(schema.$defs.BeatapiAPIKeyCredential.required).toEqual([
            'api_key',
        ]);
        expect(
            schema.$defs.BeatapiAPIKeyCredential.properties.credential_type
                .default
        ).toBe('beatapi_api_key');
        expect(meta.credentialTypes['Beatapi API Key']).toBe('beatapi_api_key');
        expect(meta.autoSelectCredential).toBe(true);
    });
    it('discovers the canvas definition in the AI category', () => {
        expect(BeatapiNode.type).toBe('automation-beatapi');
        expect(BeatapiNode.label).toBe('BeatAPI');
        expect(BeatapiNode.category).toBe('ai');
    });
});
