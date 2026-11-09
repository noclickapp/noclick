import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/langbase.json';
import { LangbaseNode } from '~/components/workflow/nodes/integrations/langbase';

describe('Langbase integration metadata and manual API-key method', () => {
  beforeAll(() => loadNodeSchemas(['automation-langbase']));
  it('discovers the account API key and class/title aliases', () => {
    expect(getNodeCredentialInfo('automation-langbase')?.acceptedTypes).toEqual(['langbase_api_key']);
    expect(getCredentialTypeFromSchemaTitle('LangbaseAPIKeyCredential')).toBe('langbase_api_key');
    expect(getCredentialTypeFromSchemaTitle('Langbase API Key')).toBe('langbase_api_key');
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    const credential = schema.$defs.LangbaseAPIKeyCredential;
    expect(credential.required).toEqual(['api_key']);
    expect(credential.properties.credential_type.default).toBe('langbase_api_key');
  });
  it('publishes AI operations with useful automation coverage', () => {
    expect(LangbaseNode.category).toBe('ai');
    const operations = getAgentToolOperations('automation-langbase').map(op => op.operation);
    expect(operations).toHaveLength(22);
    expect(operations).toEqual(expect.arrayContaining(['run_pipe', 'retrieve_memory', 'create_messages', 'embed_text', 'create_memory']));
  });
});
