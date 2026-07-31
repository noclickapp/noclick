// Verifies the config-form half of the unified form node: a LEGACY
// interface-config-form node renders as the form block (alias resolution in
// getBlockType), shows its fields with defaults, and edits persist to
// config.values — the central store downstream nodes read on every run.
import { nc } from '~/lib/nc';

export default async function () {
    const id = 'nc-test-form-store';
    // Deliberately the legacy type: pins alias-resolution through the render chain
    const added = nc.nodes.add(id, 'interface-config-form', {
        fields: [
            { name: 'channel', type: 'string', label: 'Channel', default: 'general' },
            { name: 'limit', type: 'number', label: 'Limit' },
        ],
    });
    nc.assert.truthy(added, 'harness addNode should succeed');

    try {
        await nc.wait.forElement(`[data-id="${id}"]`);
        // Alias resolution: the legacy node must render real form inputs, not GenericBlock
        await nc.wait.forElement(`[data-id="${id}"] input`);
        const inputs = [
            ...document.querySelectorAll(`[data-id="${id}"] input[type="text"], [data-id="${id}"] input[type="number"]`),
        ] as HTMLInputElement[];
        nc.assert.equal(inputs.length, 2, 'both fields should render as inputs');

        const buttons = [...document.querySelectorAll(`[data-id="${id}"] button`)].map(
            (b) => (b.textContent || '').trim(),
        );
        const hasCopyLink = buttons.includes('Copy link');
        const hasSubmit = buttons.includes('Submit');

        // Default seeded into the persisted store (nc.nodes.get returns the
        // flattened node shape — config sits top-level, not under .data)
        const readStore = (): Record<string, unknown> => {
            const n = nc.nodes.get(id) as { config?: { values?: Record<string, unknown> } } | null;
            return { ...(n?.config?.values ?? {}) };
        };
        const storedAfterMount = readStore();

        // Type into the channel field — must persist to config.values
        nc.dom.type(inputs[0], 'alerts');
        await nc.wait.ms(300);
        const storedAfterEdit = readStore();

        return {
            hasCopyLink,
            hasSubmit,
            storedAfterMount,
            storedAfterEdit,
            defaultSeeded: storedAfterMount.channel === 'general',
            editPersisted: storedAfterEdit.channel === 'alerts',
        };
    } finally {
        nc.nodes.deleteViaUI(id);
    }
}
