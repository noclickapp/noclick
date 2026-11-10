import { beforeAll, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/zyte-api.json'), 'utf8'));
beforeAll(() => loadNodeSchemas(['automation-zyte-api']));
it('offers a manually pasted API key and the extraction presets', () => {
    expect(getNodeCredentialInfo('automation-zyte-api')?.acceptedTypes).toEqual(['zyte_api_key']);
    expect(methodFromRequirement(requirementsFromSchema(schema)[0])).toMatchObject({ method_kind: 'api_key', is_oauth: false });
    expect(getAgentToolOperations('automation-zyte-api')).toHaveLength(18);
});
