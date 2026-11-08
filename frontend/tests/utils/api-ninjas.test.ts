import { beforeAll, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/api-ninjas.json'), 'utf8'));

describe('API Ninjas integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-api-ninjas']));
    it('discovers the API key and manual connection method', () => {
        expect(getNodeCredentialInfo('automation-api-ninjas')?.acceptedTypes).toEqual(['api_ninjas_api_key']);
        expect(getNodeCredentialInfo('automation-api-ninjas')?.label).toBe('API Ninjas API Key');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0])).toMatchObject({ method_kind: 'api_key', is_oauth: false });
        expect(getCredentialTypeFromSchemaTitle('ApiNinjasApiKeyCredential')).toBe('api_ninjas_api_key');
        expect(getCredentialTypeFromSchemaTitle('API Ninjas API Key')).toBe('api_ninjas_api_key');
    });
    it('exposes all fifteen published operations', () => {
        expect(getAgentToolOperations('automation-api-ninjas').map(op => op.operation)).toEqual([
            'validate_email', 'validate_phone', 'geocode', 'reverse_geocode', 'get_weather',
            'convert_currency', 'get_exchange_rate', 'get_stock_price', 'get_nutrition',
            'analyze_sentiment', 'detect_language', 'compare_text', 'generate_password', 'lookup_ip', 'get_world_time',
        ]);
    });
});
