// Uses a root-prepared owned AccuLynx node on the real primary FlowCanvas later.
// It checks the native form and official image without saving credentials or executing a CRM change.
import { nc } from '~/lib/nc';

export default async function test() {
    const node = nc.nodes.list().find(n => n.type === 'automation-acculynx' && n.data.operation === 'create_unassigned_lead');
    nc.assert.ok(node, 'Root must prepare an existing owned AccuLynx lead node');
    if (!node) return;
    nc.nodes.select(node.id);
    await nc.wait.until(() => Boolean(document.body.textContent?.includes('Confirm CRM Change')));
    nc.assert.ok(document.body.textContent?.includes('Primary Contact'), 'The actual native lead form renders');
    const image = document.querySelector<HTMLImageElement>('img[src="/icons/acculynx.svg"]');
    nc.assert.ok(image && image.complete && image.naturalWidth > 0, 'The unchanged official SVG loads');
}
