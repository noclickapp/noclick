import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, NODE_SCHEMAS, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { BenchmarkEmailClassicNode } from '~/components/workflow/nodes/integrations/benchmark-email-classic';

describe('Benchmark Email Classic', () => {
    beforeAll(() => loadNodeSchemas(['automation-benchmark-email-classic']));
    it('offers a separate marketing integration and a manual Admin API Token', () => {
        const type = BenchmarkEmailClassicNode.type;
        expect(BenchmarkEmailClassicNode.category).toBe('marketing');
        const method = methodFromRequirement(requirementsFromSchema(NODE_SCHEMAS[type])[0]);
        expect(method).toMatchObject({ method_kind: 'api_key', is_oauth: false });
        expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual(['benchmark_email_classic_api_token']);
        expect(method.credential_fields?.filter(field => field.required).map(field => field.name)).toEqual(['api_token']);
        expect(getAgentToolOperations(type)).toHaveLength(22);
    });
});
