import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '../../app/schemas/nodes/grok.json';
import { GrokNode } from '../../app/components/workflow/nodes/integrations/grok';

describe('Grok integration', () => {
    it('connects a manually pasted API key', () => {
        const methods = requirementsFromSchema(schema).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'grok_api_key', method_kind: 'api_key', is_oauth: false });
        expect(schema.$defs.GrokAPIKeyCredential.properties.api_key['ui:widget']).toBe('password');
        expect(schema.$defs.GrokAPIKeyCredential.properties.credential_type.default).toBe('grok_api_key');
    });
    it('discovers twenty operations in the AI catalog', () => {
        expect(GrokNode.type).toBe('automation-grok');
        expect(GrokNode.category).toBe('ai');
        expect(schema.properties.config.oneOf).toHaveLength(20);
    });
});
