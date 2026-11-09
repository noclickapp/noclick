import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';

const schema = JSON.parse(readFileSync(new URL('../../app/schemas/nodes/wodify-core.json', import.meta.url), 'utf8'));

describe('Wodify Core connection', () => {
    it('discovers a manually pasted API key', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-wodify-core');
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['wodify_core_api_key']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
    });
});
