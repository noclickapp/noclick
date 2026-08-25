// E2E regression guard (red→green) for the delivery-confirmed auto-resume.
// The auto-resume must NOT be fire-once: a lost workflow:builder:edit must
// trigger bounded retries instead of silently dropping the resume. Drives
// the REAL InterruptedRunBanner: injects an interrupted gen (with a prompt) for
// the active conversation, swallows the wire send (simulating the loss), and
// asserts the resume retries (>1 attempt). Pre-fix this was exactly 1.
import { activeGenStore, evictGen } from '~/lib/activeGenStore';
import { activeConversationStore } from '~/lib/activeConversationStore';
import { socketReceiver } from '~/lib/socket-receiver';
import { nc } from '~/lib/nc';

export default async function () {
  const byWf: any = (activeConversationStore as any).byWorkflow || {};
  const entries = Object.entries(byWf) as [string, string][];
  if (!entries.length) throw new Error('no active conversation bound — open a workflow chat first');
  const [workflowId, conversationId] = entries[entries.length - 1];
  const sock: any = socketReceiver.getSocket('API');

  // Swallow every workflow:builder:edit ⇒ the backend never acks (active_gen:started
  // never arrives), simulating lost delivery.
  const attempts: number[] = [];
  const origEmit = sock.emit.bind(sock);
  sock.emit = (ev: string, ...args: any[]) => {
    if (ev === 'workflow:builder:edit') { attempts.push(Date.now()); return sock; }
    return origEmit(ev, ...args);
  };

  // Inject an interrupted gen WITH a prompt → the REAL banner should auto-resume.
  const genId = 'e2e_lost_' + Date.now();
  activeGenStore.gens[genId] = {
    gen_id: genId, workflow_id: workflowId, conversation_id: conversationId,
    prompt: 'add a slack node and connect it', interrupted: true,
    started_at: Date.now() / 1000, text: '', events: [], edit_steps: [],
    status: 'Modifying workflow', lastEventAt: Date.now(),
  } as any;
  (activeGenStore.byConversation[conversationId] ||= []).push(genId);
  (activeGenStore.byWorkflow[workflowId] ||= []).push(genId);

  // Past the bounded retry window (MAX_DELIVERY_ATTEMPTS × CONFIRM_MS ≈ 3 × 3s).
  await nc.wait.ms(11000);

  sock.emit = origEmit;
  try { evictGen(genId); } catch { /* noop */ }
  delete activeGenStore.gens[genId];
  activeGenStore.byConversation[conversationId] = (activeGenStore.byConversation[conversationId] || []).filter((id) => id !== genId);
  activeGenStore.byWorkflow[workflowId] = (activeGenStore.byWorkflow[workflowId] || []).filter((id) => id !== genId);

  nc.assert.gt(attempts.length, 1, 'a lost delivery must trigger bounded retries (fire-once regression)');
  return { emitAttempts: attempts.length };
}
