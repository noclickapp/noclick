// Verifies the active-gen staleness watchdog (activeGenStore.markStaleGensInterrupted).
// A builder run whose container is drained/killed mid-stream sends no further
// frames and never emits active_gen:terminal, so without this it sits
// "streaming" forever (the 2026-06-17 stuck-on-"Modifying workflow" bug). The
// watchdog flags such a gen `interrupted` (→ chat unblocks for retry) while
// leaving a live-but-slow run alone. Added alongside that fix.
import { nc } from '~/lib/nc';
import { activeGenStore, markStaleGensInterrupted } from '~/lib/activeGenStore';

function putGen(id: string, lastEventAt: number) {
  activeGenStore.gens[id] = {
    gen_id: id, workflow_id: 'wd_wf', conversation_id: 'wd_conv', prompt: 'p',
    started_at: Date.now() / 1000, text: '', events: [], edit_steps: [],
    status: 'Modifying workflow', lastEventAt,
  } as any;
}

export default async function () {
  const created: string[] = [];
  try {
    const now = Date.now();
    const reconnectAt = now - 30_000; // socket reconnected 30s ago (> 20s grace)

    // Dead: last frame predates the reconnect and the grace has elapsed →
    // the old container is gone and no frame arrived on the new one.
    putGen('wd_dead', reconnectAt - 5_000); created.push('wd_dead');
    // Alive-but-slow: received a frame AFTER the reconnect (socket up).
    putGen('wd_alive', reconnectAt + 2_000); created.push('wd_alive');

    const marked = markStaleGensInterrupted(now, reconnectAt);
    nc.assert.includes(marked, 'wd_dead', 'post-reconnect-silent gen marked interrupted');
    nc.assert.truthy(activeGenStore.gens['wd_dead'].interrupted, 'dead gen interrupted flag set');
    nc.assert.falsy(activeGenStore.gens['wd_alive'].interrupted, 'alive-but-slow gen left streaming');

    // Absolute-silence backstop: no reconnect, but silent > 5min.
    putGen('wd_wedged', now - 6 * 60_000); created.push('wd_wedged');
    const marked2 = markStaleGensInterrupted(now, null);
    nc.assert.includes(marked2, 'wd_wedged', 'wedged gen marked via absolute-silence backstop');

    // Idempotent: an already-interrupted gen is not re-marked.
    const again = markStaleGensInterrupted(now, reconnectAt);
    nc.assert.falsy(again.includes('wd_dead'), 'already-interrupted gen not re-marked');

    return { marked, marked2, again };
  } finally {
    for (const id of created) delete activeGenStore.gens[id];
  }
}
