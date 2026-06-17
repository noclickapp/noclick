// Demo/spec for the interrupted-run render polish. composeMessages is the pure
// function that turns an active gen into the Message MessagesView draws, so its
// output is the faithful "how it looks" spec: a watchdog-interrupted gen →
// distinct "connection lost" + Retry (retryPrompt set); a user stop → the
// existing "interrupted by user" notice; a live gen → the streaming spinner.
import { composeMessages } from '~/lib/composeMessages';
import type { ActiveGeneration } from '~/lib/activeGenStore';

function gen(overrides: Partial<ActiveGeneration>): ActiveGeneration {
  return {
    gen_id: 'demo', workflow_id: 'w', conversation_id: 'c',
    prompt: 'Build a CapCut templates landing page',
    started_at: Date.now() / 1000, text: 'Building the landing page…',
    events: [], edit_steps: ['Thinking', 'Adding nodes'],
    status: 'Modifying workflow', lastEventAt: Date.now(),
    ...overrides,
  } as ActiveGeneration;
}

export default async function () {
  const pick = (msgs: any[]) => {
    const a = msgs.find(m => !m.isUser);
    return {
      isComplete: a.isComplete,
      editStatus: a.editStatus ?? null,        // non-null → live spinner shows this text
      wasInterrupted: !!a.wasInterrupted,        // → "Response interrupted by user"
      wasDisconnected: !!a.wasDisconnected,      // → amber "Connection lost…" notice
      retryPrompt: a.retryPrompt ?? null,        // → drives the Retry button
    };
  };
  return {
    disconnected: pick(composeMessages([], [gen({ interrupted: true })])),
    userStopped: pick(composeMessages([], [gen({ stopped: true })])),
    streaming: pick(composeMessages([], [gen({})])),
  };
}
