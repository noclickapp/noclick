import { describe, expect, it } from 'vitest';
import { getNodeSchema } from '~/utils/nodeSchemas';

describe('Lemlist node schema', () => {
    it('loads the generated catalog for the FlowCanvas configuration panel', () => {
        const schema = getNodeSchema('automation-lemlist');
        expect(schema?.properties?.config?.discriminator?.mapping).toBeDefined();
        expect(Object.keys(schema.properties.config.discriminator.mapping)).toHaveLength(176);
        expect(schema.properties.credentials.anyOf[0].$ref).toBe('#/$defs/LemlistApiKeyCredential');
    });
});
