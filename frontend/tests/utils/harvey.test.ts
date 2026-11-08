import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/harvey.json';

describe('Harvey native integration', () => {
  beforeAll(() => loadNodeSchemas(['automation-harvey']));
  it('discovers the hand-connected token and its aliases', () => {
    expect(getNodeCredentialInfo('automation-harvey')?.acceptedTypes).toEqual(['harvey_api_token']);
    expect(getNodeCredentialInfo('automation-harvey')?.label).toBe('Harvey API Token');
    expect(getCredentialTypeFromSchemaTitle('HarveyTokenCredential')).toBe('harvey_api_token');
    expect(getCredentialTypeFromSchemaTitle('Harvey API Token')).toBe('harvey_api_token');
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
  });
  it('exposes all 23 operations with fields isolated by operation', () => {
    expect(getAgentToolOperations('automation-harvey')).toHaveLength(23);
    expect(filterConfigForExecution('automation-harvey', {
      operation: 'get_project', project_id: 'project', request_id: 'intake', title: 'unused',
    })).toEqual({ operation: 'get_project', project_id: 'project' });
  });
});
