import { describe, expect, it } from 'vitest';
import schema from '~/schemas/nodes/sierra-interactive.json';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { SierraInteractiveNode } from '~/components/workflow/nodes/integrations/sierra-interactive';

describe('Sierra Interactive manual connection', () => {
    it('offers an API key and a CRM catalog category', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
        expect(SierraInteractiveNode.category).toBe('crm-sales');
        expect(SierraInteractiveNode.type).toBe('automation-sierra-interactive');
    });
});
