import { describe, expect, it } from 'vitest';
import { getNodeSchema, loadNodeSchemas } from '~/utils/nodeSchemas';

describe('Hunter node schema', () => {
    it('loads all 182 operations and the API key credential for FlowCanvas', async () => {
        await loadNodeSchemas(['automation-hunter']);
        const schema = getNodeSchema('automation-hunter');
        expect(schema?.properties?.config?.discriminator?.mapping).toBeDefined();
        expect(Object.keys(schema.properties.config.discriminator.mapping)).toHaveLength(182);
        expect(schema.properties.credentials.anyOf[0].$ref).toBe('#/$defs/HunterApiKeyCredential');
    });
});
