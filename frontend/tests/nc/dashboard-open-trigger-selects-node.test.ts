// Dashboard "Open trigger" must land on the trigger node with its config open.
//
// Regression: the canvas selected the node from the cache-restored graph, and
// the backend snapshot then rebuilt every node object without `selected`, so
// xyflow reported an empty selection and the config panel opened on nothing
// (2026-09-10). PRECONDITION: the seeded local workflow below (a Slack trigger
// carrying a delivery verdict) owned by the logged-in user.
import { nc } from '~/lib/nc';
import { goToWorkflowNode } from '~/lib/navigation';

const WF = '11111111-2222-4333-8444-555555555555';
const NODE = 'slack_trig';

type RawNode = { id: string; selected?: boolean; data?: Record<string, unknown> };

export default async function () {
    // The user had the workflow open earlier, so its graph sits in the
    // instant-render cache: that restore is what the server snapshot later
    // replaces. Warm it the same way, then start from the Dashboard tab.
    history.pushState({}, '', '/dashboard?tab=workflows&workflow=' + WF);
    window.dispatchEvent(new PopStateEvent('popstate'));
    await nc.wait.until(() => nc.nodes.workflowId() === WF && nc.nodes.count() >= 2, 20000);
    await nc.wait.ms(1500);
    window.dispatchEvent(new CustomEvent('noclick:switch-tab', { detail: { tab: 'dashboard' }, bubbles: true }));
    await nc.wait.ms(1200);
    const startedOn = location.search;

    goToWorkflowNode(WF, NODE); // exactly what the row's "Open trigger" calls

    await nc.wait.until(() => nc.nodes.workflowId() === WF && nc.nodes.count() >= 2, 20000);
    // Let the backend snapshot land after the cache restore, plus the panel open.
    await nc.wait.ms(4000);

    const nodes = nc.nodes.list() as RawNode[];
    const selected = nodes.filter((n) => n.selected).map((n) => n.id);
    const panel = nc.configPanel();
    const panelText = nc.dom.getText('[data-testid="subscription-status"]') ?? '';
    const emptyHint = !!nc.dom.qsa('*').find((el) => el.textContent === 'Select a node to view its configuration');
    const badge = nc.dom.qsa(`[data-id="${NODE}"] [title]`).map((el) => (el as HTMLElement).title).filter(Boolean);

    nc.assert.deepEqual(selected, [NODE], 'the trigger node is the one selected');
    nc.assert.truthy(!emptyHint, 'the config panel is not the empty "select a node" state');
    return { startedOn, workflowId: nc.nodes.workflowId(), selected, panelLabel: panel?.nodeLabel, panelText, badge, url: location.search };
}
