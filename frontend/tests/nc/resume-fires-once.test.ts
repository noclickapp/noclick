// Regression guard: the auto-resume must fire EXACTLY ONE workflow:builder:edit
// even when the backend ack (active_gen:started) never arrives. Re-emitting on a
// slow ack used to spawn duplicate backend runs (the reproduced case: 3 runs in a
// 260ms burst → 3 duplicate turns). Drives the REAL InterruptedRunBanner: injects
// one interrupted gen, swallows the wire send (so no ack is ever seen), and
// asserts a single emit.
import { activeGenStore } from '~/lib/activeGenStore';
import { activeConversationStore } from '~/lib/activeConversationStore';
import { socketReceiver } from '~/lib/socket-receiver';
import { nc } from '~/lib/nc';

export default async function () {
  const byWf: any = (activeConversationStore as any).byWorkflow || {};
  const entries = Object.entries(byWf) as [string, string][];
  if (!entries.length) throw new Error('no active conversation bound — open a workflow chat first');
  const [workflowId, conversationId] = entries[entries.length - 1];
  const sock: any = socketReceiver.getSocket('API');

  const emits: number[] = [];
  const t0 = Date.now();
  const origEmit = sock.emit.bind(sock);
  sock.emit = (ev: string, ...args: any[]) => {
    if (ev === 'workflow:builder:edit') { emits.push(Date.now() - t0); return sock; } // swallow ⇒ never acked
    return origEmit(ev, ...args);
  };

  const genId = 'fires_once_' + Date.now();
  activeGenStore.gens[genId] = {
    gen_id: genId, workflow_id: workflowId, conversation_id: conversationId,
    prompt: 'build an analytics dashboard', interrupted: true, started_at: Date.now() / 1000,
    text: 'Thinking', events: [], edit_steps: ['n1'], status: 'Modifying workflow', lastEventAt: Date.now(),
  } as any;
  (activeGenStore.byConversation[conversationId] ||= []).push(genId);
  (activeGenStore.byWorkflow[workflowId] ||= []).push(genId);

  // Past the old 3-attempt retry window (~9s) — a single fire stays 1; the old
  // loop would have re-emitted to 3 by now.
  await nc.wait.ms(11000);

  sock.emit = origEmit;
  delete activeGenStore.gens[genId];
  activeGenStore.byConversation[conversationId] = (activeGenStore.byConversation[conversationId] || []).filter((x) => x !== genId);
  activeGenStore.byWorkflow[workflowId] = (activeGenStore.byWorkflow[workflowId] || []).filter((x) => x !== genId);

  nc.assert.equal(emits.length, 1, 'auto-resume must fire exactly one workflow:builder:edit (no retry burst)');
  return { emitCount: emits.length, emitTimingsMs: emits };
}
