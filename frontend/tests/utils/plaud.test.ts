import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

await loadNodeSchemas(['automation-plaud']);

describe('Plaud connection methods', () => {
    it('offers separate manually pasted workspace and Embedded user tokens', () => {
        const methods = credentialRequirements('automation-plaud').map(methodFromRequirement);
        expect(methods.map(m => m.credential_type)).toEqual(['plaud_workspace_token', 'plaud_user_token', 'plaud_mcp']); // and its vendor's MCP server, last (backend nodes/core/vendor_mcp.py)
        for (const method of methods.slice(0, 2)) {
            expect(method).toMatchObject({ method_kind: 'api_key', is_oauth: false });
        }
    });
});
