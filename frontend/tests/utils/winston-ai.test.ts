import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/winston-ai.json';

describe('Winston AI manual connection', () => {
    it('discovers a single API key method with a default credential type', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-winston-ai');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'winston_ai_api_key', method_kind: 'api_key', is_oauth: false,
        });
        const credential = schema.$defs.WinstonAIApiKeyCredential;
        expect(credential.required).toEqual(['api_key']);
        expect(credential.properties.credential_type.default).toBe('winston_ai_api_key');
        expect(credential['x-credential-instructions']).toContain('does not run an analysis');
    });
});
