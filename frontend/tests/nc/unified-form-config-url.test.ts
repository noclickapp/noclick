// Verifies the unified form node's config panel: selecting an interface-form node
// shows the merged trigger fields (Form Title / Form URL) and the ui:loadValue
// webhook widget mints a copyable public URL from the local backend.
import { nc } from '~/lib/nc';

export default async function () {
    const id = 'nc-test-form-config';
    const added = nc.nodes.add(id, 'interface-form', {
        fields: [{ name: 'email', type: 'string', label: 'Email' }],
    });
    nc.assert.truthy(added, 'harness addNode should succeed');

    try {
        await nc.wait.forElement(`[data-id="${id}"]`);
        nc.nodes.select(id);
        // The config panel renders schema fields; wait for the Form URL label.
        await nc.wait.until(
            () => (document.body.textContent || '').includes('Form URL'),
            5000,
        );
        const panelText = document.body.textContent || '';
        const hasTitle = panelText.includes('Form Title');
        // The webhook widget fires workflow:node:load_value on render; give the
        // local backend a moment to mint and populate the readonly field.
        let mintedUrl: string | null = null;
        await nc.wait.until(() => {
            const inputs = [
                ...document.querySelectorAll('input[readonly], input[disabled]'),
            ] as HTMLInputElement[];
            const hit = inputs.find((i) => /^https?:\/\//.test(i.value));
            mintedUrl = hit?.value ?? null;
            return !!hit;
        }, 8000);
        return { hasTitle, mintedUrl };
    } finally {
        nc.nodes.deleteViaUI(id);
    }
}
