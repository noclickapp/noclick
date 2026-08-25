// The agent settings panel's CAPABILITIES section: two opt-in/out switches
// (Workflow edits → enable_prompt_builder, Email updates → enable_email_updates)
// that patch the agent node's config via patchConfig. Pins that the section
// renders and each switch flips on click (block-local truth; the string-bool
// config write and backend gating are pinned in test_agent_platform_tools.py,
// and cross-store sync is exercised by the shared canvas-sync suites).
import { nc } from '~/lib/nc';

export default async function () {
  const agent = nc.nodes.list().find((n: { type?: string }) => n.type === 'agent');
  // Non-canvas tabs (share page, provide links) must lose the first-result
  // race, not answer it.
  if (!agent) {
    await nc.wait.ms(30000);
    return { skipped: 'no canvas harness in this tab' };
  }

  nc.assert.truthy(nc.ui.clickTab('Interface'), 'Interface tab found');
  await nc.wait.forElement('[data-testid="agent-chat-capabilities-section"]', 8000);

  const get = (tid: string) => nc.dom.qs(`[data-testid="${tid}"]`) as HTMLButtonElement | null;
  const flip = async (tid: string) => {
    const was = get(tid)!.getAttribute('data-state');
    nc.dom.click(get(tid)!);
    const want = was === 'checked' ? 'unchecked' : 'checked';
    for (let i = 0; i < 15 && get(tid)!.getAttribute('data-state') !== want; i++) {
      await nc.wait.ms(200);
    }
    nc.assert.equal(get(tid)!.getAttribute('data-state'), want, `${tid} flips on click`);
  };

  nc.assert.truthy(
    !!get('agent-chat-toggle-workflow-edits') && !!get('agent-chat-toggle-email-updates'),
    'both capability switches render',
  );

  // Flip each switch and flip it back — leaves the config as found.
  await flip('agent-chat-toggle-email-updates');
  await flip('agent-chat-toggle-email-updates');
  await flip('agent-chat-toggle-workflow-edits');
  await flip('agent-chat-toggle-workflow-edits');
  return { toggles: 2, roundTrips: 2 };
}
