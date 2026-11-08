import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import schema from '~/schemas/nodes/parseur.json';

beforeAll(() => loadNodeSchemas(['automation-parseur']));
it('exposes Parseur as a manual API key with the provider label', () => {
    expect(getNodeCredentialInfo('automation-parseur')?.acceptedTypes).toEqual(['parseur_api_key']);
    expect(getNodeCredentialInfo('automation-parseur')?.label).toBe('Parseur API Key');
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    expect(getCredentialTypeFromSchemaTitle('Parseur API Key')).toBe('parseur_api_key');
});
it('makes document reads and writes available to the agent', () => {
    const operations = getAgentToolOperations('automation-parseur').map(op => op.operation);
    expect(operations).toHaveLength(23);
    expect(operations).toContain('upload_email');
    expect(operations).toContain('get_document');
    expect(operations).toContain('create_custom_download');
});
