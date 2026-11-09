// Timeero must remain manually connectable with one public API key.
// These assertions cover the generated credential method and discovery metadata.
import { describe, expect, it, vi } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/timeero.json';
import meta from '~/schemas/nodeMeta/timeero.json';

vi.mock('~/components/workflow/nodes/nodeRegistry', () => ({ AVAILABLE_NODES: [], getNodeMetadata: () => undefined }));
import { TimeeroNode } from '~/components/workflow/nodes/integrations/timeero';

describe('Timeero integration', () => {
    it('offers a manually entered API key with a default credential type', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['timeero_api_key']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
        expect(schema.$defs.TimeeroAPIKeyCredential.required).toEqual(['api_key']);
        expect(schema.$defs.TimeeroAPIKeyCredential.properties.credential_type.default).toBe('timeero_api_key');
        expect(meta.autoSelectCredential).toBe(true);
    });
    it('belongs to workforce integrations and exposes real-time triggers', () => {
        expect(TimeeroNode.type).toBe('automation-timeero');
        expect(TimeeroNode.category).toBe('hr-recruiting');
        expect(schema.$defs.TimeeroOnClockInConfig.properties.operation['x-is-trigger']).toBe(true);
        expect(schema.$defs.TimeeroOnClockOutConfig.properties.operation['x-is-trigger']).toBe(true);
    });
});
