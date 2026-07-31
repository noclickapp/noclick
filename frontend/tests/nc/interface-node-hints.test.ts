// Pins which interface nodes carry the next-step edge hint: form, multimedia,
// and file-upload (their outputs feed downstream), while display-oriented
// blocks (table, html-react) stay hint-free. Added with the 2026-07 form-node
// unification's trigger-affordance pass.
import { nc } from '~/lib/nc';

const EXPECT_HINT: Record<string, boolean> = {
    'interface-form': true,
    'interface-file': true,
    'interface-file-upload': true,
    'interface-dataframe': false,
    'interface-html-react': false,
};

export default async function () {
    const types = Object.keys(EXPECT_HINT);
    const ids = types.map((t, i) => `nc-test-hint-${i}`);
    types.forEach((t, i) =>
        nc.nodes.add(ids[i], t, {}, { x: 200 + i * 600, y: 1600 }),
    );

    try {
        await nc.wait.forElement(`[data-id="${ids[0]}"]`);
        await nc.wait.ms(400);
        const results: Record<string, boolean> = {};
        types.forEach((t, i) => {
            const root = document.querySelector(`[data-id="${ids[i]}"]`);
            results[t] = !!root?.querySelector('button[title="Add next node"]');
        });
        for (const t of types) {
            nc.assert.equal(
                results[t],
                EXPECT_HINT[t],
                `${t} should ${EXPECT_HINT[t] ? 'show' : 'not show'} the next-step hint`,
            );
        }
        return results;
    } finally {
        ids.forEach((id) => nc.nodes.deleteViaUI(id));
    }
}
