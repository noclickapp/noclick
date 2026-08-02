/**
 * Pins the post-generation transition cleanup as a PURE, merge-preserving
 * transform. It exists because the cleanup used to rebuild the node array from
 * the hook's render-lagging `nodesRef` and install it wholesale
 * (`onNodesChange(() => cleanedNodes)`), which silently reverted every store
 * write that didn't come through that hook.
 *
 * Real consequence (2026-08-02): builder credential events reach the store via
 * activeGenStore, so `<set_credentials>` was undone ~400ms after the turn
 * ended; the builder's next whole-blob persist then wrote the credential-less
 * graph to the DB, un-attaching a user's WhatsApp credential 40 seconds after
 * he confirmed it worked.
 */
import { describe, expect, it } from 'vitest';
import type { Node } from '@xyflow/react';

import { stripNodeTransitions } from '~/hooks/useCanvasWorkflowEdit';

const node = (id: string, data: Record<string, unknown>, style?: Record<string, unknown>): Node =>
    ({ id, type: 'automation-whatsapp', position: { x: 0, y: 0 }, data, style } as unknown as Node);

describe('stripNodeTransitions', () => {
    it('removes only style.transition and keeps the rest of the style', () => {
        const [out] = stripNodeTransitions([
            node('a', {}, { transition: 'all 300ms', opacity: 1 }),
        ]);
        expect(out.style).toEqual({ opacity: 1 });
    });

    it('preserves credentialIds — the field the incident lost', () => {
        const creds = { whatsapp_qr: 'e564b06a-616e-4ec5-aec9-aaeccd35ff11' };
        const [out] = stripNodeTransitions([
            node('whatsapp', { label: 'WhatsApp Messaging', credentialIds: creds },
                { transition: 'all 300ms' }),
        ]);
        expect((out.data as Record<string, unknown>).credentialIds).toEqual(creds);
    });

    it('preserves every other data field untouched', () => {
        const data = {
            label: 'WhatsApp Messaging',
            operation: 'send_text_message',
            credentialIds: { whatsapp_qr: 'x' },
            config: { agent_tool_operations: ['send_text_message'] },
        };
        const [out] = stripNodeTransitions([node('n', data, { transition: 'all 300ms' })]);
        expect(out.data).toEqual(data);
    });

    it('returns nodes without a transition unchanged (identity preserved)', () => {
        const n = node('n', { credentialIds: { whatsapp_qr: 'x' } });
        const [out] = stripNodeTransitions([n]);
        expect(out).toBe(n);
    });

    it('operates on whatever array it is given — so passing it to onNodesChange maps over the LIVE store', () => {
        // The load-bearing property: the updater is `nodes => nodes`, so
        // `onNodesChange(stripNodeTransitions)` can only ever transform current
        // state. It has no capacity to reinstate a stale snapshot.
        const live = [node('fresh', { credentialIds: { whatsapp_qr: 'just-attached' } })];
        expect(stripNodeTransitions(live)[0].data).toEqual({
            credentialIds: { whatsapp_qr: 'just-attached' },
        });
        expect(stripNodeTransitions([])).toEqual([]);
    });
});
