// Regression test: when the user navigates away from a workflow editor (e.g.
// back to the workflow browser), any open <ask/> drawer scoped to that
// workflow must close. The bridge is workflow-aware now — the input:request
// payload includes a workflowId, and the bridge subscribes to the active
// editor via useSyncExternalStore (no polling) and self-closes on mismatch.
//
// Strategy: drive the bridge directly via DOM events (the same surface the
// real flow uses) and toggle WorkflowContext to simulate the provider mount
// and unmount around it. Avoids depending on canvas mount, which is heavy.

import { nc } from '~/lib/nc';
import * as wfCtx from '~/components/workflow/WorkflowContext';
import { updateBuilderContext } from '~/lib/builder-context';

const drawerVisible = () => !!document.querySelector('[data-drawer-content]');

const FAKE_WORKFLOW_A = '00000000-0000-0000-0000-000000000aaa';
const FAKE_WORKFLOW_B = '00000000-0000-0000-0000-000000000bbb';

function dispatchInputRequest(workflowId: string | undefined) {
  document.dispatchEvent(new CustomEvent('noclick:builder:input:request', {
    detail: {
      inputs: [
        { id: 'gmail_account', label: 'Which Gmail account?', type: 'text', required: true },
      ],
      title: 'Input needed',
      generationId: 'test-gen-id',
      askId: 'test-ask-id',
      workflowId,
    },
  }));
}

export default async function () {
  const out: Record<string, unknown> = {};

  // Reset to a known state first so prior runs don't pollute.
  document.dispatchEvent(new CustomEvent('noclick:builder:input:clear'));
  await nc.wait.ms(100);

  // ── Case 1: user navigates back to workflow browser ────────────────────
  wfCtx.setCurrentWorkflowId(FAKE_WORKFLOW_A);
  updateBuilderContext({ workflowId: FAKE_WORKFLOW_A, isCanvasMounted: true });
  await nc.wait.ms(400); // subscription is synchronous; tiny gap for React render
  out.case1_afterEnter_drawerVisible = drawerVisible();

  dispatchInputRequest(FAKE_WORKFLOW_A);
  await nc.wait.ms(400);
  out.case1_afterRequest_drawerVisible = drawerVisible();
  nc.assert.equal(drawerVisible(), true, 'case1: drawer visible after input:request');

  // Provider unmounts → editor id becomes undefined. Bridge sees mismatch
  // (pending workflowId !== undefined) and self-closes — no polling lag.
  wfCtx.setCurrentWorkflowId(undefined);
  await nc.wait.ms(400);
  out.case1_afterNavAway_drawerVisible = drawerVisible();
  nc.assert.equal(
    drawerVisible(),
    false,
    'case1: drawer must close when user leaves the editor',
  );

  // ── Case 2: user switches to a different workflow editor ───────────────
  wfCtx.setCurrentWorkflowId(FAKE_WORKFLOW_A);
  await nc.wait.ms(400);
  dispatchInputRequest(FAKE_WORKFLOW_A);
  await nc.wait.ms(400);
  nc.assert.equal(drawerVisible(), true, 'case2: drawer visible after re-request');

  wfCtx.setCurrentWorkflowId(FAKE_WORKFLOW_B);
  await nc.wait.ms(400);
  out.case2_afterSwitchEditor_drawerVisible = drawerVisible();
  nc.assert.equal(
    drawerVisible(),
    false,
    'case2: drawer must close when user switches to a different editor',
  );

  // ── Case 3: editor unmount always closes the drawer ─────────────────────
  // useSidebarConversation now treats editor unmount as "start fresh
  // conversation" and dispatches noclick:builder:input:clear unconditionally.
  // The legacy "untagged drawers stay open" backwards-compat is gone — every
  // dispatch site has been migrated to include workflowId.
  wfCtx.setCurrentWorkflowId(FAKE_WORKFLOW_A);
  await nc.wait.ms(400);
  dispatchInputRequest(FAKE_WORKFLOW_A);
  await nc.wait.ms(400);
  nc.assert.equal(drawerVisible(), true, 'case3: drawer visible after request');

  wfCtx.setCurrentWorkflowId(undefined);
  await nc.wait.ms(400);
  out.case3_afterNavAway_drawerVisible = drawerVisible();
  nc.assert.equal(
    drawerVisible(),
    false,
    'case3: editor unmount must close any open drawer',
  );

  // Note: the conversation-reset-on-nav-away path (where a paused-on-ask
  // bubble triggers setMessages(DEFAULT_MESSAGES) + a new conversationId)
  // can't be exercised cleanly here — synthetic message injection through
  // the cached valtio proxy doesn't reliably propagate to NoClick's
  // useCachedValtioState snapshot in time, and the production path requires
  // an actual agent run. That behavior is covered by manual verification.

  // Cleanup so the live UI / later tests aren't polluted.
  document.dispatchEvent(new CustomEvent('noclick:builder:input:clear'));
  updateBuilderContext({ workflowId: null, workflowName: null, isCanvasMounted: false });

  return out;
}
