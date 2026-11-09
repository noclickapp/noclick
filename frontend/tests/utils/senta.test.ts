// Verifies the generated Senta credential form supports manual connection.
// Pins its catalog category and operation count to catch metadata drift.
import { describe, expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import schema from '~/schemas/nodes/senta.json';
import { SentaNode } from '~/components/workflow/nodes/integrations/senta';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

describe('Senta manual connection', () => {
    it('offers a workspace and API key in finance and accounting', () => {
        expect(SentaNode.type).toBe('automation-senta');
        expect(SentaNode.category).toBe('finance-accounting');
        expect(requirementsFromSchema(schema).map(methodFromRequirement)).toEqual([
            expect.objectContaining({ credential_type: 'senta_api_key', method_kind: 'api_key', is_oauth: false }),
        ]);
        expect(schema.$defs.SentaAPIKeyCredential.properties.api_key['ui:widget']).toBe('password');
        expect(schema.$defs.SentaAPIKeyCredential.required).toEqual(['practice', 'api_key']);
        expect(schema.$defs.SentaAPIKeyCredential.properties.credential_type.default).toBe('senta_api_key');
        expect(Object.keys(schema.properties.config.discriminator.mapping)).toHaveLength(11);
    });
});
