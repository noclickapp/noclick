import { describe, expect, it } from 'vitest';
import { filterConfigForExecution, NODE_SCHEMAS, isTriggerSource } from '~/utils/nodeSchemas';

describe('Instagram direct reads', () => {
    it('exposes a real Get Comment action with the documented identity fields', () => {
        const schema = NODE_SCHEMAS['automation-instagram'];
        const config = schema.$defs.InstagramGetCommentConfig;
        expect(config.properties.operation['x-display-name']).toBe('Get Comment');
        expect(config.required).toEqual(['comment_id']);
        expect(config.properties.fields.default).toBe('id,text,timestamp,from,media');
        expect(isTriggerSource('automation-instagram', 'get_comment')).toBe(false);
        expect(schema['x-agent-tool-provider']).toBe(true);
    });

    it('keeps the selected comment ID but drops stale write and media fields', () => {
        expect(filterConfigForExecution('automation-instagram', {
            operation: 'get_comment', comment_id: '17800123456789012',
            fields: 'id,text,from,media', media_id: 'old-media', message: 'never send',
        })).toEqual({ operation: 'get_comment', comment_id: '17800123456789012', fields: 'id,text,from,media' });
    });

    it('preserves the optional participant lookup and existing paging fields', () => {
        expect(filterConfigForExecution('automation-instagram', {
            operation: 'list_conversations', user_id: '1300000000000001',
            fields: 'id,participants', limit: 10, after: 'page-two',
            recipient_id: 'stale-recipient', message: 'never send',
        })).toEqual({ operation: 'list_conversations', user_id: '1300000000000001', fields: 'id,participants', limit: 10, after: 'page-two' });
    });
});
