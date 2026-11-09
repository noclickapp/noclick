import { beforeAll, expect, it } from 'vitest';
import { MarkupAiNode } from '~/components/workflow/nodes/integrations/markup-ai';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-markup-ai']));
it('offers Markup AI API keys through manual connect in the AI category', () => {
    expect(MarkupAiNode.type).toBe('automation-markup-ai');
    expect(MarkupAiNode.category).toBe('ai');
    const methods = credentialRequirements(MarkupAiNode.type).map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0]).toMatchObject({ credential_type: 'markup_ai_api_key', method_kind: 'api_key', is_oauth: false });
    expect(methods[0].credential_fields.map(field => field.name)).toEqual(['api_key']);
});
