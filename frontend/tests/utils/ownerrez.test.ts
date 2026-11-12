import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/ownerrez.json';

describe('OwnerRez connection and operations', () => {
    beforeAll(() => loadNodeSchemas(['automation-ownerrez']));
    it('offers a personal token with a default credential type', () => {
        expect(getNodeCredentialInfo('automation-ownerrez')?.acceptedTypes).toEqual(['ownerrez_personal_token', 'ownerrez_mcp']); // and its vendor's MCP server, last (backend nodes/core/vendor_mcp.py)
        expect(methodFromRequirement(requirementsFromSchema(schema)[0])).toMatchObject({method_kind: 'api_key', is_oauth: false});
        expect(schema.$defs.OwnerRezPersonalTokenCredential.properties.credential_type.default).toBe('ownerrez_personal_token');
    });
    it('exposes twenty contracted operations', () => {
        const operations = getAgentToolOperations('automation-ownerrez').map(op => op.operation);
        expect(operations).toHaveLength(20);
        expect(operations).toEqual(expect.arrayContaining(['get_current_user', 'create_booking', 'update_booking', 'get_calendar', 'create_quote', 'add_tag']));
    });
});
