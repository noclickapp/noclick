// Prepared UNRUN; generated native schema and a separate frontend lane required.
import { beforeAll, describe, expect, it } from 'vitest';
import schema from '~/schemas/nodes/talkjs.json';
import { getNodeSchema, getNodeCredentialInfo, getAgentToolOperations, loadNodeSchemas } from '~/utils/nodeSchemas';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
const operations = ['test_connection', 'list_users', 'get_user', 'sync_user', 'list_conversations', 'list_user_conversations', 'get_conversation', 'create_conversation', 'update_conversation_metadata', 'delete_conversation', 'get_participation', 'list_messages', 'get_message', 'send_message', 'update_message', 'delete_message'];
describe('native TalkJS prepared contracts', () => {
  beforeAll(() => loadNodeSchemas(['automation-talkjs']));
  it('discovers current server-secret family and 16 native typed operations', () => {
    expect(getNodeSchema('automation-talkjs')).toEqual(schema);
    expect(getNodeCredentialInfo('automation-talkjs')?.acceptedTypes).toEqual(['talkjs_server_secret']);
    expect(CREDENTIAL_TYPE_MAP.TalkJSServerSecretCredential).toBe('talkjs_server_secret');
    expect(humanizeCredentialLabel('TalkJSServerSecret')).toBe('Talk JS Server Secret');
    const defs = schema.$defs as Record<string, any>;
    expect(Object.values(defs).filter(d => d.properties?.operation?.const).map(d => d.properties.operation.const).sort()).toEqual([...operations].sort());
    expect(defs.TalkJSServerSecretCredential.properties.server_secret['ui:widget']).toBe('password');
    expect(defs.TalkJSServerSecretCredential['x-credential-instructions']).toContain('without sub');
    expect(defs.TalkJSServerSecretCredential).not.toHaveProperty('x-oauth-provider');
    expect(defs.TalkJSCreateConversationConfig.properties.participant_ids['ui:widget']).toBe('list');
    expect(defs.TalkJSUpdateMessageConfig.properties.custom_metadata_json['ui:widget']).toBe('textarea');
    expect(defs.TalkJSSendMessageConfig.properties.confirm_changes.default).toBe(false);
    expect(defs.TalkJSListMessagesConfig.properties.include_text.default).toBe(false);
    expect(defs.TalkJSListConversationsConfig.properties.limit.maximum).toBe(30);
  });
  it('selects current owned TalkJS credentials and declares closed operation fields', () => {
    const own = 'talkjs-owned', foreign = 'talkjs-foreign';
    try {
      upsertCredentialsIntoCache([{ id: own, name: 'Owned', credential_type: 'talkjs_server_secret', owned_by_me: true }, { id: foreign, name: 'Foreign', credential_type: 'talkjs_server_secret', owned_by_me: false }]);
      expect(autoSelectCredentialFromCache('automation-talkjs')).toEqual({ talkjs_server_secret: own });
      const defs = schema.$defs as Record<string, any>;
      const cfg = defs.TalkJSUpdateConversationConfig;
      expect(cfg.additionalProperties).toBe(false);
      expect(cfg.properties).toHaveProperty('conversation_id');
      expect(cfg.properties).toHaveProperty('metadata_mode');
      for (const key of ['participants', 'url', 'server_secret', 'jwt', 'notify']) expect(cfg.properties).not.toHaveProperty(key);
    } finally { removeCredentialsFromCache([own, foreign]); }
  });
  it('retains conversation and message parent scope in actual Agent metadata', () => {
    const defs = schema.$defs as Record<string, any>;
    expect(defs.TalkJSGetMessageConfig.properties.message_id['x-dynamic-options'].depends_on).toBe('conversation_id');
    const tools = getAgentToolOperations('automation-talkjs');
    expect(tools.map(t => t.operation).sort()).toEqual([...operations].sort());
    expect(tools.find(t => t.operation === 'get_message')!.scopableFields).toEqual(expect.arrayContaining([
      expect.objectContaining({ field: 'conversation_id', resourceType: 'talkjs_conversation' }),
      expect.objectContaining({ field: 'message_id', resourceType: 'talkjs_message', dependsOn: 'conversation_id' }),
    ]));
    expect(tools.find(t => t.operation === 'send_message')!.scopableFields).toEqual(expect.arrayContaining([expect.objectContaining({ field: 'sender_id', resourceType: 'talkjs_user', dependsOn: 'conversation_id' })]));
    for (const op of ['arbitrary_request', 'create_key', 'rotate_key', 'invite_user', 'join_conversation', 'change_access', 'mark_read', 'upload_file', 'billing']) expect(operations).not.toContain(op);
  });
});
