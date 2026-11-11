// The dashboard's icon map is a file of its own: the same for every visitor, kept for good (by the browser and the CDN)
// under its version.
import { describe, expect, it } from 'vitest';
import { getAllSerializedNodeMeta, getNodeIconsFile } from '~/lib/nodeCatalog.server';
import { loader } from '~/routes/api/node-icons.$version';

const get = (version: string) => loader({ params: { version }, request: new Request(`http://x/api/node-icons/${version}`), context: {} } as unknown as Parameters<typeof loader>[0]);

describe('the node icon map as a file', () => {
    it('answers the map under its version, cached for good', async () => {
        const { version } = getNodeIconsFile();
        expect(version).toMatch(/^[0-9a-f]{16}$/);
        const res = get(version);
        expect(res.headers.get('Cache-Control')).toBe('public, max-age=31536000, s-maxage=31536000, immutable');
        expect(res.headers.get('Content-Type')).toBe('application/json');
        expect(await res.json()).toEqual(getAllSerializedNodeMeta());
    });

    it('answers another version with today’s map, never cached under it', async () => {
        const res = get('0000000000000000');
        expect(res.headers.get('Cache-Control')).toBe('no-store');
        expect(Object.keys(await res.json()).length).toBe(Object.keys(getAllSerializedNodeMeta()).length);
    });
});
