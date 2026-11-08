import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { TwoChatNode } from '~/components/workflow/nodes/integrations/2chat';

describe('2Chat native integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-2chat']));

    it('discovers the published brand and API-key method', async () => {
        const { default: schema } = await import('~/schemas/nodes/2chat.json');
        expect(TwoChatNode.type).toBe('automation-2chat');
        expect(TwoChatNode.label).toBe('2Chat');
        expect(getNodeCredentialInfo('automation-2chat')?.acceptedTypes).toEqual(['2chat_api_key']);
        expect(getCredentialTypeFromSchemaTitle('TwoChatAPIKeyCredential')).toBe('2chat_api_key');
        expect(getCredentialTypeFromSchemaTitle('2Chat API Key')).toBe('2chat_api_key');
        expect(requirementsFromSchema(schema).map(methodFromRequirement)).toEqual([
            expect.objectContaining({ method_kind: 'api_key', is_oauth: false }),
        ]);
    });

    it('exposes fixed account, contacts, messages and tag operations', () => {
        const operations = getAgentToolOperations('automation-2chat').map(op => op.operation);
        expect(operations).toHaveLength(25);
        expect(operations).toEqual(expect.arrayContaining([
            'get_account', 'create_contact', 'send_message', 'send_sms', 'add_conversation_tag',
        ]));
        expect(operations).not.toContain('custom_request');
    });
});
