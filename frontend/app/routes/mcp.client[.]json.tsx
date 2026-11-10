// NoClick's Client ID Metadata Document at /mcp/client.json: an MCP authorization server that takes CIMD fetches this
// URL as NoClick's client id (backend nodes/oauth/mcp_connect.py names it), from whichever origin the sign-in returns to.
import type { LoaderFunctionArgs } from 'react-router';
import { mcpClientMetadata } from '~/lib/mcpCallback';

export function loader({ request }: LoaderFunctionArgs) {
    return Response.json(mcpClientMetadata(new URL(request.url).origin), {
        headers: {
            'Cache-Control':
                'public, s-maxage=3600, stale-while-revalidate=86400',
        },
    });
}
