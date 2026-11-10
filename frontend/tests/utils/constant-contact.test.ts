import { describe, expect, it } from 'vitest';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/constant-contact.json';
import { ConstantContactNode } from '~/components/workflow/nodes/integrations/constant-contact';

describe('Constant Contact metadata', () => {
    it('offers OAuth and belongs to marketing', () => {
        expect(requirementsFromSchema(schema).map(r => methodFromRequirement(r).method_kind)).toEqual(['oauth']);
        expect(ConstantContactNode.category).toBe('marketing');
    });
});
