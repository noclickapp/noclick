import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
import { beforeAll, describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/stream-chat.json';
import meta from '~/schemas/nodeMeta/stream-chat.json';
import { NODE_SCHEMAS, getAgentToolOperations, loadNodeSchemas } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { StreamChatNode } from '~/components/workflow/nodes/integrations/stream-chat';

const expected = ['get_channel', 'get_channel_type', 'get_message', 'get_or_create_private_channel',
    'get_user', 'list_channel_members', 'list_channel_types', 'list_channels',
    'list_message_history', 'list_messages', 'list_users', 'rename_channel', 'upsert_user'].sort();
const defs = schema.$defs as Record<string, any>;

describe('native Stream Chat source and generated UI', () => {
    beforeAll(() => loadNodeSchemas(['automation-stream-chat']));
    it('exposes only the 13 native operations with no trigger or client token action', () => {
        expect(NODE_SCHEMAS['automation-stream-chat']).toBe(schema);
        expect(meta.nodeMeta).toEqual({ agentToolProvider: true });
        const operations = getAgentToolOperations('automation-stream-chat');
        expect(operations.map(op => op.operation).sort()).toEqual(expected);
        expect(schema['x-agent-tool-provider']).toBe(true);
        expect(JSON.stringify(schema)).not.toContain('x-is-trigger');
    });
    it('maps the explicit server key family and preserves the reviewed display label', () => {
        expect(CREDENTIAL_TYPE_MAP['Stream Chat Server Key']).toBe('stream_chat_api_key');
        expect(CREDENTIAL_TYPE_MAP.StreamChatServerCredential).toBe('stream_chat_api_key');
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['stream_chat_api_key']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
        expect(humanizeCredentialLabel(defs.StreamChatServerCredential.title)).toBe('Stream Chat Server Key');
        for (const field of ['api_key', 'api_secret']) expect(defs.StreamChatServerCredential.properties[field]['ui:widget']).toBe('password');
        expect(JSON.stringify(defs.StreamChatServerCredential)).not.toContain('x-oauth');
        expect(defs.StreamChatServerCredential.properties).not.toHaveProperty('server_jwt');
    });
    it('retains the real parent selector chain and explicit private-type confirmation', () => {
        const props = defs.GetMessageConfig.properties;
        expect(props.channel_id['x-dynamic-options'].depends_on).toBe('channel_type');
        expect(props.message_id['x-dynamic-options'].depends_on).toBe('channel_id');
        expect(defs.GetOrCreatePrivateChannelConfig.properties.member_restricted_type_confirmed.const).toBe(true);
        expect(JSON.stringify(schema)).not.toContain('x-creator');
        expect(defs.ListUsersConfig.properties.limit.maximum).toBe(100);
    });
    it('registers the native editor component and exact official product SVG bytes', () => {
        expect(StreamChatNode.type).toBe('automation-stream-chat');
        expect(StreamChatNode.label).toBe('Stream Chat');
        expect(StreamChatNode.component).toBeTruthy();
        const bytes = readFileSync(resolve(__dirname, '../../public/icons/stream-chat.svg'));
        expect(bytes.length).toBe(1164);
        expect(createHash('sha256').update(bytes).digest('hex')).toBe('98da32f528baec2bf83b08fc258415568719f11d44d385bd0022ff875fa9a70d');
    });
});
