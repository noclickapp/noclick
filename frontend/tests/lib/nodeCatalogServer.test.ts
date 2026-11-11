// Every dashboard document carries the icon map, which is the same for every request: it's built once per server
// process, never per request (building it walks every node's credential schema).
import { describe, expect, it } from 'vitest';
import { getAllSerializedNodeMeta } from '~/lib/nodeCatalog.server';

describe('getAllSerializedNodeMeta', () => {
    it('builds the icon map once and hands every request the same one', () => {
        const first = getAllSerializedNodeMeta();
        expect(Object.keys(first).length).toBeGreaterThan(100);
        expect(getAllSerializedNodeMeta()).toBe(first);
    });
});
