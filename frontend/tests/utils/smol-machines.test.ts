import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/smol-machines.json';
import { SmolMachinesNode } from '~/components/workflow/nodes/integrations/smol-machines';

describe('Smol Machines credentials', () => {
    it('discovers a pasted API key and the cloud hosting category', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-smol-machines');
        expect(SmolMachinesNode.category).toBe('cloud-hosting');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'smol_machines_api_key', method_kind: 'api_key', is_oauth: false,
        });
    });
});
