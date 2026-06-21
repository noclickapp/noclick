// Regression test for auto-expanding the desktop chat sidebar so a builder
// interaction is actually visible. Covers two wirings added together:
//   (1) "Ask AI" on the node execution-error banner dispatches noclick:builder:ask,
//       whose NoClick handler now expands the sidebar before submitting.
//   (2) A builder <ask> surfacing dispatches noclick:builder:ask:open (BuilderInputBridge),
//       which Dashboard now uses to expand the sidebar on desktop (it only redirected mobile before).
// Both reuse the canonical noclick:sidebar:expand event. Added because an Ask-AI
// flow or a surfaced ask that lands in a collapsed sidebar is invisible to the user.
import { nc } from '~/lib/nc';

// Desktop chat sidebar collapses by hiding the expanded content under a `.hidden`
// wrapper (NoClick renders expandedContent in a hidden div when !isExpanded).
const isCollapsed = (): boolean =>
    !!document.querySelector('[data-onboarding="chat"]')?.closest('.hidden');

export default async function () {
    const out: Record<string, unknown> = {};

    // This behavior is desktop-only — on mobile the chat is a separate view, not a
    // collapsible sidebar, and the `.hidden` signal doesn't apply.
    if (window.innerWidth < 768) {
        out.inconclusive = true;
        out.note = 'mobile viewport — desktop sidebar auto-expand not applicable';
        return out;
    }
    if (!document.querySelector('[data-onboarding="chat"]')) {
        out.inconclusive = true;
        out.note = 'chat sidebar not mounted — open the dashboard before running';
        return out;
    }

    const collapse = async () => {
        document.dispatchEvent(new CustomEvent('noclick:sidebar:collapse'));
        await nc.wait.ms(150);
    };

    // Defense-in-depth: a real edit must never escape during the Ask-AI probe.
    let realEditFired = false;
    const editSpy = () => { realEditFired = true; };
    document.addEventListener('noclick:workflow:edit', editSpy);

    // Stub the pending-ask store so handleWorkflowEditSubmit early-returns into a
    // harmless input:submit-message no-op (no matching drawer) instead of kicking
    // off a real headless generation.
    const savedPending = window.__noclickPendingBuilderAsk ?? null;

    try {
        // --- Task 1: "Ask AI" banner → noclick:builder:ask → sidebar expands ---
        window.__noclickPendingBuilderAsk = { workflowId: null, conversationId: '__probe__', askId: '__probe__' };
        await collapse();
        out.task1_collapsedBefore = isCollapsed();
        document.dispatchEvent(new CustomEvent('noclick:builder:ask', {
            detail: { message: 'Help me fix this error in the **Probe** node', nodeId: 'probe' },
        }));
        await nc.wait.ms(200);
        out.task1_expandedAfter = !isCollapsed();
        out.task1_noRealEditEscaped = !realEditFired;
        window.__noclickPendingBuilderAsk = savedPending;

        // --- Task 2: surfaced <ask> → noclick:builder:ask:open → sidebar expands ---
        await collapse();
        out.task2_collapsedBefore = isCollapsed();
        document.dispatchEvent(new CustomEvent('noclick:builder:ask:open'));
        await nc.wait.ms(200);
        out.task2_expandedAfter = !isCollapsed();

        nc.assert.truthy(out.task1_collapsedBefore, 'Task 1: sidebar should start collapsed');
        nc.assert.truthy(out.task1_expandedAfter, 'Task 1: noclick:builder:ask must expand the sidebar');
        nc.assert.truthy(out.task1_noRealEditEscaped, 'Task 1: stubbed ask must not start a real edit/generation');
        nc.assert.truthy(out.task2_collapsedBefore, 'Task 2: sidebar should start collapsed');
        nc.assert.truthy(out.task2_expandedAfter, 'Task 2: noclick:builder:ask:open must expand the sidebar on desktop');
        out.passed = true;
    } finally {
        document.removeEventListener('noclick:workflow:edit', editSpy);
        window.__noclickPendingBuilderAsk = savedPending;
    }
    return out;
}
