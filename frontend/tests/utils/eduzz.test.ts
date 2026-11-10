import { beforeAll, describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '../../app/schemas/nodes/eduzz.json';
import { EduzzNode } from '~/components/workflow/nodes/integrations/eduzz';
import { NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';

describe('Eduzz integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-eduzz']));
    it('discovers a manual masked application access token', () => {
        expect(NODE_SCHEMAS['automation-eduzz']).toBe(schema);
        expect(CREDENTIAL_TYPE_MAP.EduzzAccessTokenCredential).toBe('eduzz_access_token');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0])).toMatchObject({
            method_kind: 'api_key', is_oauth: false, credential_type: 'eduzz_access_token',
        });
        const credential = schema.$defs.EduzzAccessTokenCredential;
        expect(credential.required).toEqual(['access_token']);
        expect(credential.properties.credential_type.default).toBe('eduzz_access_token');
        expect(credential.properties.access_token['ui:widget']).toBe('password');
    });
    it('categorizes the learning platform and exposes API managed event triggers', () => {
        expect(EduzzNode.category).toBe('courses');
        expect(schema.$defs.EduzzOnEventConfig.properties.operation['x-is-trigger']).toBe(true);
        expect(schema.$defs.EduzzOnEventConfig.properties.event_type.enum).toContain('myeduzz.invoice_paid');
        expect(schema.$defs.EduzzCancelSubscriptionsConfig.properties.subscriptions['ui:widget']).toBe('list');
        expect(schema.$defs.EduzzCreateSchoolStudentConfig.properties.tags['ui:widget']).toBe('list');
    });
});
