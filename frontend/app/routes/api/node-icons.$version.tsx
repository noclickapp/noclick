// The node icon map the dashboard loads beside its HTML (`lib/nodeIconRegistry.loadPreloadedNodeIcons`). It's the
// same for every visitor, so a browser and the CDN keep it for good under its version; any other version gets today's,
// uncached.
import type { LoaderFunctionArgs } from 'react-router';
import { getNodeIconsFile } from '~/lib/nodeCatalog.server';

export function loader({ params }: LoaderFunctionArgs) {
    const { version, body } = getNodeIconsFile();
    return new Response(body, {
        headers: {
            'Content-Type': 'application/json',
            'Cache-Control': params.version === version ? 'public, max-age=31536000, s-maxage=31536000, immutable' : 'no-store',
        },
    });
}
