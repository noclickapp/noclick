import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

await loadNodeSchemas(['automation-plaud']);

describe('Plaud connection methods', () => {
    it('offers separate manually pasted workspace and Embedded user tokens', () => {
        const methods = credentialRequirements('automation-plaud').map(methodFromRequirement);
        expect(methods).toHaveLength(2);
        expect(methods.map(m => m.credential_type)).toEqual(['plaud_workspace_token', 'plaud_user_token']);
        for (const method of methods) {
            expect(method).toMatchObject({ method_kind: 'api_key', is_oauth: false });
        }
    });
});
