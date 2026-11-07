import { beforeAll, describe, expect, it } from 'vitest';
import schema from '~/schemas/nodes/homebase.json';
import { HomebaseNode } from '~/components/workflow/nodes/integrations/homebase';
import { NODE_SCHEMAS, loadNodeSchemas, getAgentToolOperations, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

const type = 'automation-homebase';
describe('Homebase self-registering integration', () => {
    beforeAll(() => loadNodeSchemas([type]));
    it('discovers its definition, schema and native API key method', () => {
        expect(HomebaseNode.type).toBe(type);
        expect(NODE_SCHEMAS[type]).toBe(schema);
        expect(CREDENTIAL_TYPE_MAP.HomebaseApiKeyCredential).toBe('homebase_api_key');
        expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual(['homebase_api_key']);
        expect(humanizeCredentialLabel(schema.$defs.HomebaseApiKeyCredential.title)).toBe('Homebase API Key');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
        expect(schema.$defs.HomebaseApiKeyCredential.properties.api_key['ui:widget']).toBe('password');
    });
    it('exposes four closed reads and a typed location selector', () => {
        expect(getAgentToolOperations(type)).toHaveLength(4);
        expect(schema.$defs.GetEmployee.properties.location_uuid['x-dynamic-options']).toMatchObject({ field_name: 'location_uuid' });
        expect(schema.$defs.GetEmployee.properties.location_uuid.format).toBe('uuid');
        expect(schema.$defs.GetEmployee.properties.employee_id['x-resource-type']).toBe('homebase_employee');
        expect(schema.$defs.HomebaseApiKeyCredential.required).toEqual(expect.arrayContaining(['api_key', 'expected_company_name', 'expected_company_owner_id', 'allowed_location_uuids']));
    });
});
