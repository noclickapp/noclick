// Resource route: the node search catalog the canvas palettes search (utils/nodeSearchCatalog). The same for
// everyone, so browsers and the CDN keep it; its ETag changes only when a node or schema does.
import { createHash } from 'node:crypto';
import type { LoaderFunctionArgs } from 'react-router';
import { nodeSearchCatalogJson } from '~/lib/nodeSearchCatalog.server';

let _etag: string | null = null;

export function loader({ request }: LoaderFunctionArgs) {
    const json = nodeSearchCatalogJson();
    _etag ??= `"${createHash('sha256').update(json).digest('base64url').slice(0, 27)}"`;
    const headers = {
        'Content-Type': 'application/json; charset=utf-8',
        'Cache-Control': 'public, max-age=300, s-maxage=86400, stale-while-revalidate=604800',
        ETag: _etag,
    };
    if (request.headers.get('If-None-Match') === _etag) return new Response(null, { status: 304, headers });
    // Streamed: the catalog is larger than a function's buffered response may be.
    const bytes = new TextEncoder().encode(json);
    const CHUNK = 1 << 20;
    let offset = 0;
    const body = new ReadableStream<Uint8Array>({
        pull(controller) {
            if (offset >= bytes.length) {
                controller.close();
                return;
            }
            controller.enqueue(bytes.subarray(offset, offset + CHUNK));
            offset += CHUNK;
        },
    });
    return new Response(body, { headers });
}
