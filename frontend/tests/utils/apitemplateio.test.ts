import { expect, it } from 'vitest';
import schema from '~/schemas/nodes/apitemplateio.json';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

it('offers a manually entered API key with a default type and region', () => {
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    expect(schema.$defs.APITemplateIOApiKey.required).toEqual(['api_key']);
    expect(schema.$defs.APITemplateIOApiKey.properties.credential_type.default).toBe('apitemplateio_api_key');
    expect(schema.$defs.APITemplateIOApiKey.properties.region.default).toBe('singapore');
});
