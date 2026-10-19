// Verifies the usage-based billing credentials UI on a credential-optional Exa operation: the panel says the account
// is optional and that NoClick's own key runs it and bills the usage, while the way to connect your own key stays
// on screen; a BYOK-only operation drops that note. Added with the Exa platform-key billing path.
import { nc } from '~/lib/nc';

const NODE_ID = 'debug-exa-cred-ui';
const OPTIONAL_NOTE = 'Optional. With no account here, NoClick’s own key runs it and bills the usage.';

export default async function () {
    if (!nc.nodes.workflowId()) {
        return { skipped: 'No workflow open — open a workflow, then re-run.' };
    }

    const area = () => document.querySelector(`[data-credentials-area="${NODE_ID}"]`);
    const panelText = () => area()?.textContent ?? '';

    const openCredentialsTab = () => {
        const tab = Array.from(document.querySelectorAll('button')).find(
            b => b.textContent?.trim() === 'Credentials' || b.getAttribute('aria-label') === 'Credentials'
        );
        if (!tab) return false;
        tab.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        return true;
    };

    try {
        nc.nodes.add(NODE_ID, 'automation-exa', { operation: 'search', query: 'test' });
        nc.nodes.select(NODE_ID);
        // Selecting doesn't open the node's panel; a click on the node does.
        await nc.wait.until(() => !!document.querySelector(`.react-flow__node[data-id="${NODE_ID}"]`));
        document.querySelector(`.react-flow__node[data-id="${NODE_ID}"]`)?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        await nc.wait.until(openCredentialsTab);
        await nc.wait.until(() => panelText().length > 0);

        const optionalText = panelText();
        nc.assert.ok(optionalText.includes(OPTIONAL_NOTE), `optional note shown for search op (got: ${optionalText.slice(0, 200)})`);
        // Your own key can still be connected: the key's form (or an account picker) stays rendered.
        const byokVisible = !!area()?.querySelector('form') || !!area()?.querySelector('[data-testid="credential-dropdown"]');
        nc.assert.ok(byokVisible, 'BYOK connect form or picker still rendered');

        // BYOK-only op: no optional note.
        nc.nodes.update(NODE_ID, { operation: 'create_webset', config: { operation: 'create_webset', query: 'x' } });
        await nc.wait.until(() => !panelText().includes(OPTIONAL_NOTE));
        nc.assert.ok(!!area()?.querySelector('form'), 'BYOK-only op still offers the key form');

        return { ok: true };
    } finally {
        nc.nodes.delete(NODE_ID);
    }
}
