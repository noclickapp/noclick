// Live check of the Microsoft organization-wide admin consent affordance: an Excel
// node's Credentials tab renders "approve NoClick for your organization" beside the
// Connect button, and clicking it opens the SAME authorize route with admin_consent=1
// plus the node's own scopes and a type-specific credential name. window.open is
// stubbed so no popup is spawned; the captured URL is the assertion.
import { nc } from '~/lib/nc';

const NODE_ID = 'debug-excel-org-consent';
const LINK_RE = /approve NoClick for your organization/i;

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
    const orgLink = () =>
        Array.from(area()?.querySelectorAll('button') ?? []).find(b => LINK_RE.test(b.textContent ?? ''));

    const realOpen = window.open;
    const opened: string[] = [];
    const fakePopup = { closed: false, close() { this.closed = true; } };
    window.open = ((url: string | URL) => { opened.push(String(url)); return fakePopup as unknown as Window; }) as typeof window.open;

    try {
        nc.nodes.add(NODE_ID, 'automation-excel', { operation: 'create_workbook_session' });
        // A canvas click (not the select event) is what opens the node panel with its tabs.
        await nc.wait.until(() => nc.nodes.click(NODE_ID));
        await nc.wait.until(openCredentialsTab);
        await nc.wait.until(() => /Connect .*Account/.test(panelText()), 8000);

        const connectBtn = Array.from(area()!.querySelectorAll('button')).find(b => /Connect .*Account/.test(b.textContent ?? ''));
        nc.assert.ok(!!connectBtn, `Connect button rendered (panel: ${panelText().slice(0, 160)})`);
        nc.assert.ok(!!orgLink(), 'org-consent link rendered next to Connect');

        orgLink()!.click();
        await nc.wait.until(() => opened.length > 0, 3000);

        const url = new URL(opened[0], location.origin);
        nc.assert.equal(url.pathname, '/api/auth/microsoft/authorize', 'same authorize route');
        nc.assert.equal(url.searchParams.get('admin_consent'), '1', 'admin_consent=1 set');
        const scopes = url.searchParams.get('scopes') ?? '';
        nc.assert.ok(scopes.includes('https://graph.microsoft.com/Files.ReadWrite.All'), `Excel scopes carried (${scopes})`);
        nc.assert.ok(scopes.includes('offline_access'), 'provider extra scopes appended');
        const name = url.searchParams.get('name') ?? '';
        nc.assert.ok(/excel/i.test(name), `type-specific credential name (${name})`);

        // While the (fake) popup is open the link yields to the Connecting state.
        await nc.wait.until(() => /Connecting/.test(panelText()), 3000);
        nc.assert.ok(!orgLink(), 'link hidden while connecting');

        // Closing the popup returns the form to idle with the closed-early error and the link back.
        fakePopup.close();
        await nc.wait.until(() => !!orgLink(), 5000);
        nc.assert.ok(/closed before finishing/.test(panelText()), 'popup-closed error surfaced');

        return { ok: true, openedUrl: opened[0] };
    } finally {
        window.open = realOpen;
        nc.nodes.delete(NODE_ID);
    }
}
