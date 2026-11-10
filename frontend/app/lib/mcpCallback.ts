// Where an MCP server's sign-in returns (routes/api/auth/mcp.callback.tsx) and what that page sends back, on the
// state's BroadcastChannel and to its opener; and NoClick's Client ID Metadata Document (routes/mcp.client[.]json.tsx),
// which an MCP authorization server that takes CIMD fetches as the client. The backend registers the callback with a
// vendor and names the document as the client id (backend nodes/oauth/mcp_connect.py).
export const MCP_CALLBACK_PATH = '/api/auth/mcp/callback';
export const MCP_CALLBACK_TYPE = 'mcp-oauth-callback';
export const MCP_CLIENT_METADATA_PATH = '/mcp/client.json';

/** The document for the app served at `origin`: its URL is the client id, and its one redirect URI is this origin's
 *  callback, so a server knows the sign-in can only return here. */
export function mcpClientMetadata(origin: string) {
    return {
        client_id: `${origin}${MCP_CLIENT_METADATA_PATH}`,
        client_name: 'NoClick',
        client_uri: origin,
        logo_uri: `${origin}/favicon.ico`,
        redirect_uris: [`${origin}${MCP_CALLBACK_PATH}`],
        grant_types: ['authorization_code', 'refresh_token'],
        response_types: ['code'],
        token_endpoint_auth_method: 'none',
    };
}
