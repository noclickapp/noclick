// Verifies the unified form node's Copy link button (InterfaceFormLinkButton):
// an interface-form block on the canvas renders a "Copy link" pill in its header,
// styled like the publish button. Added with the 2026-07 form-node unification.
import { nc } from '~/lib/nc';

export default async function () {
    const id = 'nc-test-unified-form';
    const added = nc.nodes.add(id, 'interface-form', {
        fields: [{ name: 'email', type: 'string', label: 'Email', required: true }],
    });
    nc.assert.truthy(added, 'harness addNode should succeed');

    try {
        await nc.wait.forElement(`[data-id="${id}"]`);
        const buttons = [
            ...document.querySelectorAll(`[data-id="${id}"] button`),
        ].map((b) => (b.textContent || '').trim());
        nc.assert.truthy(
            buttons.includes('Copy link'),
            `form block header should show a Copy link button (got: ${buttons.join(', ')})`,
        );
        // The form block itself should render its field + submit affordance.
        const blockText = nc.dom.getText(`[data-id="${id}"]`) ?? '';
        nc.assert.truthy(blockText.includes('Email'), 'form field label should render');

        // Trigger affordances, matching other trigger nodes: amber bolt on the
        // left replacing the input handle, next-step hint on the right.
        const root = document.querySelector(`[data-id="${id}"]`)!;
        nc.assert.truthy(root.querySelector('[title^="Trigger"]'), 'trigger bolt badge should render');
        nc.assert.truthy(
            !root.querySelector('.react-flow__handle-left.target, .react-flow__handle.target'),
            'input handle should be hidden (nothing flows into a trigger)',
        );
        nc.assert.truthy(
            root.querySelector('button[title="Add next node"]'),
            'unconnected form should show the next-step hint',
        );
        return { buttons };
    } finally {
        nc.nodes.deleteViaUI(id);
    }
}
