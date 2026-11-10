// NoClick's Client ID Metadata Document (/mcp/client.json): an MCP authorization server that takes CIMD fetches it as
// NoClick's client, so its client_id is its own URL and its one redirect URI is the callback on the same origin. The
// backend names both paths (nodes/oauth/mcp_connect.py); they must be the ones this app serves.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { loader } from '~/routes/mcp.client[.]json';
import { MCP_CALLBACK_PATH, MCP_CLIENT_METADATA_PATH } from '~/lib/mcpCallback';

describe('the MCP client metadata document', () => {
    it('names itself as the client and its own origin’s callback', async () => {
        const response = loader({
            request: new Request('https://staging.example.test/mcp/client.json'),
            params: {},
            context: {},
        } as never);
        expect(response.headers.get('Cache-Control')).toContain('public');
        expect(await response.json()).toEqual({
            client_id: 'https://staging.example.test/mcp/client.json',
            client_name: 'NoClick',
            client_uri: 'https://staging.example.test',
            logo_uri: 'https://staging.example.test/favicon.ico',
            redirect_uris: [
                'https://staging.example.test/api/auth/mcp/callback',
            ],
            grant_types: ['authorization_code', 'refresh_token'],
            response_types: ['code'],
            token_endpoint_auth_method: 'none',
        });
    });

    it('is served where the backend says it is', () => {
        const backend = readFileSync(
            join(__dirname, '../../../backend/nodes/oauth/mcp_connect.py'),
            'utf8'
        );
        expect(backend).toContain(`CALLBACK_PATH = "${MCP_CALLBACK_PATH}"`);
        expect(backend).toContain(
            `CLIENT_METADATA_PATH = "${MCP_CLIENT_METADATA_PATH}"`
        );
    });
});
