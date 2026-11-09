import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { MailsoftlyNode } from '~/components/workflow/nodes/integrations/mailsoftly';

describe('Mailsoftly native integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-mailsoftly']));

    it('discovers the published brand and API-key method', async () => {
        const { default: schema } = await import('~/schemas/nodes/mailsoftly.json');
        expect(MailsoftlyNode.type).toBe('automation-mailsoftly');
        expect(MailsoftlyNode.label).toBe('Mailsoftly');
        expect(getNodeCredentialInfo('automation-mailsoftly')?.acceptedTypes).toEqual(['mailsoftly_api_key']);
        expect(getCredentialTypeFromSchemaTitle('MailsoftlyAPIKeyCredential')).toBe('mailsoftly_api_key');
        expect(getCredentialTypeFromSchemaTitle('Mailsoftly API Key')).toBe('mailsoftly_api_key');
        expect(requirementsFromSchema(schema).map(methodFromRequirement)).toEqual([
            expect.objectContaining({ method_kind: 'api_key', is_oauth: false }),
        ]);
    });

    it('exposes fixed account, contacts, messages and tag operations', () => {
        const operations = getAgentToolOperations('automation-mailsoftly').map(op => op.operation);
        expect(operations).toHaveLength(23);
        expect(operations).toEqual(expect.arrayContaining([
            'get_account', 'create_contact', 'get_contacts', 'list_campaigns', 'assign_tag_to_contact',
        ]));
        expect(operations).not.toContain('custom_request');
    });
});
