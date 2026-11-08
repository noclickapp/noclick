import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { FlatfileNode } from '../../app/components/workflow/nodes/integrations/flatfile';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas, NODE_SCHEMAS } from '../../app/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '../../app/utils/credentialTypeMap';
import metadata from '../../app/schemas/nodeMeta/flatfile.json';

await loadNodeSchemas(['automation-flatfile']);

describe('Flatfile integration', () => {
  it('discovers the categorized native definition and all operations', () => {
    expect(FlatfileNode.type).toBe('automation-flatfile');
    expect(FlatfileNode.category).toBe('developer-tools');
    expect(getAgentToolOperations('automation-flatfile')).toHaveLength(24);
    expect(metadata.nodeMeta.agentToolProvider).toBe(true);
  });

  it('connects manually with one secret key and its default type', () => {
    expect(credentialRequirements('automation-flatfile').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
    expect(getNodeCredentialInfo('automation-flatfile')?.acceptedTypes).toEqual(['flatfile_api_key']);
    expect(getCredentialTypeFromSchemaTitle('Flatfile API Key')).toBe('flatfile_api_key');
    const credential = NODE_SCHEMAS['automation-flatfile'].$defs.FlatfileApiKeyCredential;
    expect(credential.properties.credential_type.default).toBe('flatfile_api_key');
    expect(credential.required).toEqual(['api_key']);
    expect(credential.properties.api_key['ui:widget']).toBe('password');
    expect(metadata.providerLabels.flatfile).toBe('Flatfile API Key');
  });
});
