import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/breezy-hr.json';

beforeAll(() => loadNodeSchemas(['automation-breezy-hr']));

it('discovers a manual token credential with the provider label', () => {
  expect(getNodeCredentialInfo('automation-breezy-hr')?.acceptedTypes).toEqual(['breezy_hr_api_token']);
  expect(getNodeCredentialInfo('automation-breezy-hr')?.label).toBe('Breezy HR API Token');
  expect(getCredentialTypeFromSchemaTitle('BreezyHRTokenCredential')).toBe('breezy_hr_api_token');
  expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
});

it('exposes 20 operations and filters unrelated write fields', () => {
  expect(getAgentToolOperations('automation-breezy-hr')).toHaveLength(20);
  expect(filterConfigForExecution('automation-breezy-hr', {
    operation: 'set_candidate_stage', company_id: 'company', position_id: 'position',
    candidate_id: 'candidate', stage_id: 'hired', name: 'unrelated',
  })).toEqual({ operation: 'set_candidate_stage', company_id: 'company', position_id: 'position', candidate_id: 'candidate', stage_id: 'hired' });
});
