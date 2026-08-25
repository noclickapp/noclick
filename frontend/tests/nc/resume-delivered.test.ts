// Happy-path guard for the delivery-confirmed auto-resume: when the backend
// acks (active_gen:started arrives), the resume must make EXACTLY ONE emit (no
// over-retry → no duplicate runs) and evict the dead gen. Swallows the wire send
// but injects a backend-style gen shortly after the first emit to simulate the
// ack. Pairs with resume-race-probe.test.ts (the lost-delivery → retry case).
import { activeGenStore } from '~/lib/activeGenStore';
import { activeConversationStore } from '~/lib/activeConversationStore';
import { socketReceiver } from '~/lib/socket-receiver';
import { nc } from '~/lib/nc';

export default async function () {
  const byWf: any = (activeConversationStore as any).byWorkflow || {};
  const entries = Object.entries(byWf) as [string, string][];
  if (!entries.length) return { error: 'no active conversation bound — open a workflow chat first' };
  const [workflowId, conversationId] = entries[entries.length - 1];
  const sock: any = socketReceiver.getSocket('API');

  const attempts: number[] = [];
  let firstSeen = false;
  const ackId = 'backend_ack_' + Date.now();
  const origEmit = sock.emit.bind(sock);
  sock.emit = (ev: string, ...args: any[]) => {
    if (ev === 'workflow:builder:edit') {
      attempts.push(Date.now());
      if (!firstSeen) {
        firstSeen = true;
        // Simulate the backend's early active_gen:started ack after delivery.
        setTimeout(() => {
          activeGenStore.gens[ackId] = {
            gen_id: ackId, workflow_id: workflowId, conversation_id: conversationId,
            prompt: 'x', started_at: Date.now() / 1000, text: '', events: [],
            edit_steps: [], status: 'Modifying workflow', lastEventAt: Date.now(),
          } as any;
          (activeGenStore.byConversation[conversationId] ||= []).push(ackId);
          (activeGenStore.byWorkflow[workflowId] ||= []).push(ackId);
        }, 600);
      }
      return sock; // swallow the wire send
    }
    return origEmit(ev, ...args);
  };

  const genId = 'e2e_delivered_' + Date.now();
  activeGenStore.gens[genId] = {
    gen_id: genId, workflow_id: workflowId, conversation_id: conversationId,
    prompt: 'add a slack node', interrupted: true, started_at: Date.now() / 1000,
    text: '', events: [], edit_steps: [], status: 'Modifying workflow', lastEventAt: Date.now(),
  } as any;
  (activeGenStore.byConversation[conversationId] ||= []).push(genId);
  (activeGenStore.byWorkflow[workflowId] ||= []).push(genId);

  await nc.wait.ms(6000);

  const deadGenEvicted = !activeGenStore.gens[genId];

  sock.emit = origEmit;
  for (const id of [genId, ackId]) {
    delete activeGenStore.gens[id];
    activeGenStore.byConversation[conversationId] = (activeGenStore.byConversation[conversationId] || []).filter((x) => x !== id);
    activeGenStore.byWorkflow[workflowId] = (activeGenStore.byWorkflow[workflowId] || []).filter((x) => x !== id);
  }

  nc.assert.equal(attempts.length, 1, 'a confirmed delivery must make exactly one attempt (no duplicate runs)');
  nc.assert.truthy(deadGenEvicted, 'the dead gen must be evicted once the resume takes hold');
  return {
    emitAttempts: attempts.length,
    deliveredOnFirstAttempt: attempts.length === 1,
    deadGenEvicted,
  };
}
