import { beforeAll, describe, expect, it } from 'vitest';
import { AccredibleCertificatesNode } from '~/components/workflow/nodes/integrations/accredible-certificates';
import { NODE_SCHEMAS, loadNodeSchemas, getAgentToolOperations, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const type = 'automation-accredible-certificates';
describe('Accredible Certificates', () => {
    beforeAll(() => loadNodeSchemas([type]));
    it('discovers the definition and a pasted API key connection', () => {
        expect(AccredibleCertificatesNode.type).toBe(type);
        expect(AccredibleCertificatesNode.label).toBe('Accredible Certificates');
        expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual(['accredible_certificates_api_key']);
        const methods = requirementsFromSchema(NODE_SCHEMAS[type]).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ method_kind: 'api_key', is_oauth: false });
    });
    it('exposes certificate, group and account resource operations', () => {
        expect(getAgentToolOperations(type)).toHaveLength(19);
    });
});
