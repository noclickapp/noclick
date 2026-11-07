// Sirv's supplied-token method and closed read catalog, adapted from #2684.
import { beforeAll, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';

beforeAll(() => loadNodeSchemas(['automation-sirv']));

it('discovers the native supplied-token method without an OAuth flow', () => {
    expect(getCredentialTypeFromSchemaTitle('SirvAccessTokenCredential')).toBe('sirv_access_token');
    expect(getCredentialTypeFromSchemaTitle('Sirv Access Token')).toBe('sirv_access_token');
    expect(getNodeCredentialInfo('automation-sirv')?.acceptedTypes).toEqual(['sirv_access_token']);
    const methods = credentialRequirements('automation-sirv').map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0].method_kind).toBe('api_key');
    expect(methods[0].is_oauth).toBe(false);
    expect(methods[0].credential_fields.map(field => field.name).sort()).toEqual(['access_token', 'expires_at', 'root_folder', 'scope']);
});

it('exposes only the five native metadata reads', () => {
    expect(getAgentToolOperations('automation-sirv').map(op => op.operation).sort()).toEqual([
        'get_file_approval', 'get_file_info', 'get_file_metadata', 'get_folder_options', 'list_folder',
    ]);
});
