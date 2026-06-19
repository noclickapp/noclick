// @vitest-environment jsdom
// Characterizes the double/triple resume-bubble bug at the authoritative layer:
// composeMessages is the pure function that projects (persisted history + active
// gens) → the chat Message[] (bubbles). N concurrent prompted resume gens render
// N user bubbles — exactly the duplication seen on resumption.
import { it, expect } from 'vitest';
import { composeMessages } from '~/lib/composeMessages';

const gen = (id: string, prompt: string, interrupted = false): any => ({
  gen_id: id, workflow_id: 'w', conversation_id: 'c', prompt, interrupted,
  started_at: 1, text: '', events: [], edit_steps: [], status: 'Modifying workflow', lastEventAt: 1,
});
const userBubbles = (msgs: any[], text: string) => msgs.filter((m) => m.isUser && m.text === text).length;

it('renders one user bubble per concurrent resume run (the double/triple-bubble bug + fire-once fix)', () => {
  const P = 'build a dashboard';
  // BUG: the delivery-confirmed retry fired up to 3 workflow:builder:edit emits,
  // so 3 concurrent prompted resume gens coexisted with the interrupted one. The
  // composeMessages continuation dedupe (#1397) only collapses the ADJACENT
  // dead+resume1 pair, so the chat still showed 3 (and 2) user bubbles.
  expect(userBubbles(composeMessages([], [gen('d', P, true), gen('r1', P), gen('r2', P), gen('r3', P)]), P)).toBe(3);
  expect(userBubbles(composeMessages([], [gen('d', P, true), gen('r1', P), gen('r2', P)]), P)).toBe(2);
  // FIX: fire-once (the fire-once regression fix) guarantees exactly ONE resume gen → dead+resume
  // collapse to a single turn → one bubble.
  expect(userBubbles(composeMessages([], [gen('d', P, true), gen('r1', P)]), P)).toBe(1);
});
