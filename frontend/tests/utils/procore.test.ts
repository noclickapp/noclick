// Verify Procore discovery, catalog placement and its OAuth connection method.
// These checks protect the metadata consumed by the shared connection UI.
import { beforeAll, describe, expect, it } from 'vitest';
import { ProcoreNode } from '~/components/workflow/nodes/integrations/procore';
import { NODE_SCHEMAS, loadNodeSchemas, getAgentToolOperations, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const type = 'automation-procore';
describe('Procore', () => {
    beforeAll(() => loadNodeSchemas([type]));
    it('discovers the industry integration and Procore OAuth method', () => {
        expect(ProcoreNode.type).toBe(type);
        expect(ProcoreNode.category).toBe('industry');
        expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual(['procore_oauth']);
        const methods = requirementsFromSchema(NODE_SCHEMAS[type]).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ method_kind: 'oauth', is_oauth: true });
    });
    it('exposes 22 company, project, directory and construction operations', () => {
        expect(getAgentToolOperations(type)).toHaveLength(22);
    });
});
