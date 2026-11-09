// Pins the Nifty catalog entry and its manual personal-token connection form.
// This catches metadata drift that could hide the integration or break hand-connecting.
import { describe, expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import schema from '~/schemas/nodes/nifty-pm.json';
import { NiftyPMNode } from '~/components/workflow/nodes/integrations/nifty-pm';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

describe('Nifty manual connection', () => {
    it('offers a pasted token and a productivity catalog entry', () => {
        expect(NiftyPMNode.type).toBe('automation-nifty-pm');
        expect(NiftyPMNode.category).toBe('productivity');
        expect(requirementsFromSchema(schema).map(methodFromRequirement)).toEqual([
            expect.objectContaining({ credential_type: 'nifty_pm_personal_access_token', method_kind: 'api_key', is_oauth: false }),
        ]);
        expect(schema.$defs.NiftyPMTokenCredential.properties.access_token['ui:widget']).toBe('password');
        expect(schema.$defs.NiftyPMTokenCredential.required).toEqual(['access_token']);
        expect(Object.keys(schema.properties.config.discriminator.mapping)).toHaveLength(23);
    });
});
