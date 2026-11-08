import { beforeAll, describe, expect, it } from 'vitest';
import { DockCertsNode } from '~/components/workflow/nodes/integrations/dock-certs';
import {
    NODE_SCHEMAS,
    loadNodeSchemas,
    getAgentToolOperations,
    getNodeCredentialInfo,
} from '~/utils/nodeSchemas';
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';

const type = 'automation-dock-certs';
describe('Dock Certs integration', () => {
    beforeAll(() => loadNodeSchemas([type]));
    it('offers a manual API key with an environment choice', () => {
        const schema = NODE_SCHEMAS[type];
        expect(DockCertsNode.category).toBe('documents');
        expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual([
            'dock_certs_api_key',
        ]);
        const methods = requirementsFromSchema(schema).map(
            methodFromRequirement
        );
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({
            method_kind: 'api_key',
            is_oauth: false,
        });
        const credential = schema.$defs.DockCertsAPIKeyCredential;
        expect(credential.required).toEqual(['api_key']);
        expect(credential.properties.credential_type.default).toBe(
            'dock_certs_api_key'
        );
        expect(credential.properties.api_key['ui:widget']).toBe('password');
        expect(credential.properties.environment.enum).toEqual([
            'production',
            'sandbox',
        ]);
    });
    it('discovers 25 bounded operations', () => {
        expect(getAgentToolOperations(type)).toHaveLength(25);
        expect(DockCertsNode.keywords).toContain('Truvera');
    });
});
