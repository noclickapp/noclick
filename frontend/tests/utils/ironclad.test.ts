import { describe, expect, it } from 'vitest';
import { IroncladNode } from '~/components/workflow/nodes/integrations/ironclad';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

describe('Ironclad integration', () => {
    it('discovers the node and pasted token method', async () => {
        expect(IroncladNode.type).toBe('automation-ironclad');
        expect(IroncladNode.label).toBe('Ironclad');
        await loadNodeSchemas([IroncladNode.type]);
        const methods = credentialRequirements(IroncladNode.type).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'ironclad_api_token', method_kind: 'api_key', is_oauth: false });
    });
});
