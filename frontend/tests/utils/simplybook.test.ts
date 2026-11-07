import { beforeAll, describe, expect, it } from 'vitest';
import { NODE_DEFINITION_FILES } from '~/components/workflow/nodes/nodeDefinitions';
import { loadNodeSchemas, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';

beforeAll(() => loadNodeSchemas(['automation-simplybook']));

describe('SimplyBook.me native integration', () => {
    it('discovers the canvas definition and all four field-based auth methods', () => {
        expect(NODE_DEFINITION_FILES).toContainEqual(['automation-simplybook', 'integrations/simplybook']);
        const types = ['simplybook_company_api_key', 'simplybook_admin_user', 'simplybook_company_token', 'simplybook_admin_token'];
        expect(getNodeCredentialInfo('automation-simplybook')?.acceptedTypes).toEqual(types);
        const methods = credentialRequirements('automation-simplybook').map(methodFromRequirement);
        expect(methods.map(method => method.credential_type)).toEqual(types);
        expect(methods.every(method => method.method_kind === 'api_key' && !method.is_oauth)).toBe(true);
        expect(getCredentialTypeFromSchemaTitle('simplybook.me Admin Token')).toBe('simplybook_admin_token');
        expect(getCredentialTypeFromSchemaTitle('SimplyBookCompanyAPIKeyCredential')).toBe('simplybook_company_api_key');
    });
});
