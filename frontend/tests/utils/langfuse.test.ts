// Verifies Langfuse manual connection fields and catalog placement. These checks keep the public connect form aligned with the generated credential schema.
import { beforeAll, describe, expect, it } from 'vitest';
import {
    credentialRequirements,
    methodFromRequirement,
} from '~/components/credential/credentialMethods';
import { loadAllNodeSchemas } from '~/utils/nodeSchemas';
import { LangfuseNode } from '~/components/workflow/nodes/integrations/langfuse';

describe('Langfuse integration', () => {
    beforeAll(async () => {
        await loadAllNodeSchemas();
    });
    it('offers manual project keys with all required fields and region', () => {
        const methods = credentialRequirements('automation-langfuse').map(
            methodFromRequirement
        );
        expect(methods).toHaveLength(1);
        expect(methods[0].method_kind).toBe('api_key');
        expect(methods[0].is_oauth).toBe(false);
        expect(methods[0].credential_fields?.map((f) => f.name)).toEqual([
            'public_key',
            'secret_key',
            'region',
        ]);
        expect(
            methods[0].credential_fields
                ?.filter((f) => f.required)
                .map((f) => f.name)
        ).toEqual(['public_key', 'secret_key']);
    });
    it('belongs in the AI catalog', () => {
        expect(LangfuseNode.type).toBe('automation-langfuse');
        expect(LangfuseNode.category).toBe('ai');
    });
});
