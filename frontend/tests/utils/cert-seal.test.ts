import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { CertSealNode } from '../../app/components/workflow/nodes/integrations/cert-seal';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-cert-seal']);

describe('Cert Seal', () => {
    it('publishes certificate operations in the documents catalog', () => {
        expect(CertSealNode.type).toBe('automation-cert-seal');
        expect(CertSealNode.category).toBe('documents');
        const operations = getAgentToolOperations('automation-cert-seal').map(o => o.operation);
        expect(operations).toHaveLength(17);
        expect(operations).toContain('create_recipients_bulk');
        expect(operations).toContain('send_recipient');
        expect(operations).toContain('revoke_recipient');
        expect(operations).toContain('get_certificate_by_code');
    });
    it('supports a manually pasted workspace API key', () => {
        expect(credentialRequirements('automation-cert-seal').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-cert-seal')?.acceptedTypes).toContain('cert_seal_api_key');
    });
});
