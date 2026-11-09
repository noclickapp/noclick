import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
import { ChiliPiperNode } from '~/components/workflow/nodes/integrations/chili-piper';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/chili-piper.json'), 'utf8'));

describe('Chili Piper', () => {
    it('offers a manually connected API key and provider instructions', () => {
        const methods = requirementsFromSchema(schema).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'chili_piper_api_key', method_kind: 'api_key', is_oauth: false });
        const credential = schema.$defs.ChiliPiperAPIKey;
        expect(credential.title).toBe('Chili Piper API Key');
        expect(credential.properties.credential_type.default).toBe('chili_piper_api_key');
        expect(credential.required).toEqual(['api_key']);
        expect(credential.properties.api_key['ui:widget']).toBe('password');
        expect(credential['x-credential-instructions']).toContain('Admin Center');
        expect(credential['x-credential-instructions']).toContain('Bearer');
    });

    it('lists the integration under meetings with its official icon', () => {
        expect(ChiliPiperNode.type).toBe('automation-chili-piper');
        expect(ChiliPiperNode.category).toBe('meetings');
        expect(ChiliPiperNode.label).toBe('Chili Piper');
    });
});
