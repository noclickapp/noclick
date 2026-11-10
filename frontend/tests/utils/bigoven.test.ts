import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/bigoven.json';

describe('BigOven native integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-bigoven']));
    it('offers a pasted key and account with all manual fields', () => {
        expect(getNodeCredentialInfo('automation-bigoven')?.acceptedTypes).toEqual(['bigoven_api_key']);
        const method = methodFromRequirement(requirementsFromSchema(schema)[0]);
        expect(method.method_kind).toBe('api_key');
        expect(method.credential_fields.map(f => f.name)).toEqual(['api_key', 'username', 'password']);
    });
    it('offers 24 native operations', () => {
        const operations = getAgentToolOperations('automation-bigoven').map(op => op.operation);
        expect(operations).toHaveLength(24);
        expect(operations).toEqual(expect.arrayContaining(['get_me', 'search_recipes', 'create_recipe', 'add_grocery_item', 'clear_checked_items']));
    });
});
