// Regression guard for the resume duplication bug: an auto-resume re-submits
// the interrupted run's ORIGINAL prompt, and composeMessages must render that as
// a continuation of the dead turn (extend the trailing assistant) instead of a
// second [user, asst] turn — otherwise the prompt shows twice and the two
// simultaneously-streaming turns can drive a React #185 render loop. Pure-
// function test over composeMessages, plus guards that a genuinely re-typed
// prompt (after a COMPLETED turn) is NOT merged.
import { composeMessages } from '~/lib/composeMessages';
import { nc } from '~/lib/nc';

const mkGen = (id: string, prompt: string, interrupted: boolean) => ({
  gen_id: id, workflow_id: 'w', conversation_id: 'c', prompt, interrupted,
  started_at: 1, text: 'x', events: [], edit_steps: [], status: 'Modifying workflow', lastEventAt: 1,
});
const userCount = (msgs: any[], text: string) => msgs.filter((m) => m.isUser && m.text === text).length;

export default async function () {
  const P = 'build a dashboard';
  // Resume re-submits the interrupted prompt → ONE user bubble (continuation).
  const resume = userCount(composeMessages([], [mkGen('d', P, true) as any, mkGen('r', P, false) as any]), P);
  // Re-typing the same prompt after a COMPLETED (not interrupted) turn → TWO (no false merge).
  const retype = userCount(composeMessages([], [mkGen('a', P, false) as any, mkGen('b', P, false) as any]), P);
  // Distinct prompts each render once even when the prior was interrupted.
  const both = composeMessages([], [mkGen('a', 'P1', true) as any, mkGen('b', 'P2', false) as any]);

  nc.assert.equal(resume, 1, 'resume of an interrupted run must render as a continuation (no duplicate user bubble)');
  nc.assert.equal(retype, 2, 're-typing a prompt after a completed turn must NOT be merged');
  nc.assert.equal(userCount(both, 'P1'), 1, 'distinct prompt P1 renders once');
  nc.assert.equal(userCount(both, 'P2'), 1, 'distinct prompt P2 renders once (not merged into the interrupted P1)');

  return { resume, retype, p1: userCount(both, 'P1'), p2: userCount(both, 'P2') };
}
