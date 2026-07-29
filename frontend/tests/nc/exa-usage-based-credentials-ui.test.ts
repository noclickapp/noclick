// Verifies the standardized usage-based billing credentials UI (agent-style)
// on a credential-optional Exa operation: the BYOK picker stays visible with a
// green "usage-based billing available" marker and a "Using NoClick's
// usage-based billing" note, while BYOK-only ops keep the required-credentials
// rendering. Added with the Exa platform-key billing path.
import { nc } from '~/lib/nc';

const NODE_ID = 'debug-exa-cred-ui';

export default async function () {
    if (!nc.nodes.workflowId()) {
        return { skipped: 'No workflow open — open a workflow, then re-run.' };
    }

    const panelText = () =>
        (document.querySelector(`[data-credentials-area="${NODE_ID}"]`)?.textContent ?? '');

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
        await nc.wait.until(openCredentialsTab);
        await nc.wait.until(() => panelText().length > 0);

        const optionalText = panelText();
        nc.assert.ok(
            optionalText.includes('Usage-based billing available'),
            `green optional marker shown for search op (got: ${optionalText.slice(0, 200)})`
        );
        nc.assert.ok(
            optionalText.includes("Using NoClick's usage-based billing"),
            'NoClick-billing note shown when no credential attached'
        );
        nc.assert.ok(
            optionalText.includes('API Credentials') && !optionalText.includes('Required Credentials'),
            'header reads API Credentials for an optional op'
        );
        const byokVisible =
            !!document.querySelector(`[data-credentials-area="${NODE_ID}"] [data-testid="credential-dropdown"]`) ||
            optionalText.includes('Create new');
        nc.assert.ok(byokVisible, 'BYOK picker/create entry still rendered');

        // BYOK-only op keeps the required rendering.
        nc.nodes.update(NODE_ID, { operation: 'create_webset', config: { operation: 'create_webset', query: 'x' } });
        await nc.wait.until(() => panelText().includes('Required Credentials'));
        nc.assert.ok(
            !panelText().includes('Usage-based billing available'),
            'no optional marker on a BYOK-only op'
        );

        return { ok: true };
    } finally {
        nc.nodes.delete(NODE_ID);
    }
}
