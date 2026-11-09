import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-polymarket-us']));

it('discovers the Polymarket US signing key as a manual API key method', () => {
    expect(getCredentialTypeFromSchemaTitle('PolymarketUSAPIKeyCredential')).toBe('polymarket_us_api_key');
    expect(getCredentialTypeFromSchemaTitle('Polymarket US API Key')).toBe('polymarket_us_api_key');
    expect(getNodeCredentialInfo('automation-polymarket-us')?.acceptedTypes).toEqual(['polymarket_us_api_key']);
    const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-polymarket-us']);
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
    expect(methodFromRequirement(requirements[0]).is_oauth).toBe(false);
});
