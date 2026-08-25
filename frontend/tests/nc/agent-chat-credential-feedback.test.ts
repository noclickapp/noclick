// Regression test: a missing agent credential must give VISIBLE feedback in
// the agent chat — a standing amber hint above the composer, and the red
// error banner on an attempted send — instead of the send silently no-oping
// (the empty state used to render instead of the transcript that owns the
// banner, so a failed pre-flight showed nothing at all).
import { nc } from '~/lib/nc';

export default async function () {
  const agent = nc.nodes.list().find((n: { type?: string }) => n.type === 'agent');
  // Every open tab runs the test and the FIRST nc:result wins (vite-plugin).
  // Tabs without the canvas harness (e.g. the public share page) must LOSE
  // that race, not answer it — hold their skip back long enough for the
  // dashboard tab's real result to land first.
  if (!agent) {
    await nc.wait.ms(10000);
    return { skipped: 'no canvas harness in this tab' };
  }
  const id = agent.id as string;
  const config = ((agent.data as Record<string, unknown> | undefined)?.config ?? {}) as Record<string, unknown>;
  const originalCreds = (config.credentialIds ?? {}) as Record<string, string>;

  nc.assert.truthy(nc.ui.clickTab('Interface'), 'Interface tab found');
  await nc.wait.forElement('textarea', 8000);

  // The hint may legitimately already show (the active conversation locks its
  // harness; a resumed thread can demand a different provider than the linked
  // credential). Snapshot the initial state; the restore step must return to it.
  const hintBefore = !!nc.dom.qs('[data-testid="agent-chat-credential-hint"]');

  try {
    // Strip the credential link LOCALLY (nc mutators don't broadcast).
    nc.nodes.update(id, { config: { credentialIds: {} } });
    await nc.wait.forElement('[data-testid="agent-chat-credential-hint"]', 4000);

    // Attempted send: raises the red banner with the fix actions, and must NOT
    // echo the user bubble (nothing was dispatched).
    const textarea = nc.dom.qs('textarea') as HTMLTextAreaElement | null;
    nc.assert.truthy(!!textarea, 'composer textarea present');
    nc.dom.type(textarea!, 'credential feedback probe');
    await nc.wait.ms(200);
    nc.assert.equal(textarea!.value, 'credential feedback probe', 'draft registered');
    const sendBtn = nc.dom.qs('button[aria-label="Send"]') as HTMLButtonElement | null;
    nc.assert.truthy(!!sendBtn, 'send button present');
    nc.assert.truthy(!sendBtn!.disabled, 'send button enabled with a draft');
    nc.dom.click(sendBtn!);
    await nc.wait.forElement('[data-testid="agent-chat-error"]', 4000);
    nc.assert.truthy(
      !!nc.dom.qs('[data-testid="agent-chat-error-add-credential"]'),
      'banner carries the Add credential action',
    );
    nc.assert.truthy(
      !(document.body.innerText || '').includes('credential feedback probe\n'),
      'blocked send must not echo a user bubble',
    );
    return { hint: true, banner: true };
  } finally {
    // Restore the link; the hint must return to its initial state (the
    // credentialIds change also clears the banner via the clear-on-fix effect).
    nc.nodes.update(id, { config: { credentialIds: originalCreds } });
    await nc.wait.ms(300);
    const hintAfter = !!nc.dom.qs('[data-testid="agent-chat-credential-hint"]');
    nc.assert.equal(hintAfter, hintBefore, 'hint returns to its pre-test state');
  }
}
