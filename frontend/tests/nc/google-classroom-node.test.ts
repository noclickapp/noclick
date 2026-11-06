// Run against an authenticated FlowCanvas with nc_run_test. The live OAuth and
// execution paths are checked separately with a connected Classroom account.
import { nc } from '~/lib/nc';

export default async function () {
    nc.ui.clickTab('canvas');
    const id = 'nc-google-classroom-smoke';
    nc.nodes.delete(id);
    nc.assert.truthy(
        nc.nodes.add(id, 'automation-google-classroom', { operation: 'list_courses' }),
        'Google Classroom node should be addable to the canvas',
    );
    try {
        await nc.wait.forElement(`[data-id="${id}"]`);
        const icon = document.querySelector<HTMLImageElement>(
            `[data-id="${id}"] img[src="/icons/google-classroom-preferred-brand.svg"]`,
        );
        nc.assert.truthy(icon, 'canvas node should render the Classroom SVG');
        const node = nc.nodes.get(id) as { operation?: string } | null;
        nc.assert.equal(node?.operation, 'list_courses', 'selected operation should persist');
    } finally {
        nc.nodes.deleteViaUI(id);
    }
}
