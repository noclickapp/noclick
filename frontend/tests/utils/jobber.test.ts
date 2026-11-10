import { beforeAll, describe, expect, it } from 'vitest';
import { JobberNode } from '~/components/workflow/nodes/integrations/jobber';
import {
    NODE_SCHEMAS,
    loadNodeSchemas,
    getAgentToolOperations,
} from '~/utils/nodeSchemas';
import {
    requirementsFromSchema,
    methodFromRequirement,
} from '~/components/credential/credentialMethods';

const type = 'automation-jobber';
describe('Jobber integration', () => {
    beforeAll(() => loadNodeSchemas([type]));
    it('discovers ten actions and the declared OAuth sign-in', () => {
        expect(JobberNode.type).toBe(type);
        expect(JobberNode.category).toBe('industry');
        const methods = requirementsFromSchema(NODE_SCHEMAS[type]).map(
            methodFromRequirement
        );
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({
            credential_type: 'jobber_oauth',
            method_kind: 'oauth',
            is_oauth: true,
        });
        expect(getAgentToolOperations(type)).toHaveLength(10);
    });
});
