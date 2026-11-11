import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-funtranslations']));
it('offers the pasted FunTranslations API key and translation operations', () => {
    expect(getNodeCredentialInfo('automation-funtranslations')?.acceptedTypes).toEqual(['funtranslations_api_key']);
    expect(getCredentialTypeFromSchemaTitle('FunTranslations API Key')).toBe('funtranslations_api_key');
    expect(credentialRequirements('automation-funtranslations').map(methodFromRequirement).map(method => method.method_kind)).toEqual(['api_key']);
    const operations = getAgentToolOperations('automation-funtranslations').map(op => op.operation);
    expect(operations).toHaveLength(24);
    expect(operations).toContain('translate_yoda');
    expect(operations).toContain('translate_morse2english');
    expect(operations).toContain('check_connection');
});
