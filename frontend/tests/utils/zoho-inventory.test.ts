import { describe, expect, it } from 'vitest';
import schema from '../../app/schemas/nodes/zoho-inventory.json';
import metadata from '../../app/schemas/nodeMeta/zoho-inventory.json';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

describe('Zoho Inventory credential metadata', () => {
    it('connects through the declared OAuth provider', () => {
        const methods = requirementsFromSchema(schema).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'zoho_inventory_oauth', method_kind: 'oauth', is_oauth: true });
        expect(Object.keys(schema.$defs).filter(key => key.includes('CreatedOrUpdatedConfig'))).toHaveLength(4);
        expect(metadata.oauthProviders[0]).toMatchObject({ provider: 'zoho_inventory', credentialType: 'zoho_inventory_oauth', scopeSeparator: ',' });
    });
});
