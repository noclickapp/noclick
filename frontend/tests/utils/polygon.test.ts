import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/polygon.json'), 'utf8'));
describe('Polygon connect method', () => {
  it('offers a manually pasted key with reachability evidence', () => {
    const methods = requirementsFromSchema(schema).map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0]).toMatchObject({ credential_type: 'polygon_api_key', method_kind: 'api_key', is_oauth: false });
    const credential = schema.$defs.PolygonAPIKeyCredential;
    expect(credential.title).toBe('Polygon API Key');
    expect(credential.properties.api_key['ui:widget']).toBe('password');
    expect(credential.properties.credential_type.default).toBe('polygon_api_key');
    expect(credential.required).toEqual(['api_key']);
    expect(credential['x-credential-instructions']).toContain('not account identity');
  });
});
