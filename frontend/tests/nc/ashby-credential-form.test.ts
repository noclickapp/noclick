// Run while authenticated on /dashboard. Verifies the generated Ashby
// credential form without creating or saving an API key.
import { nc } from '~/lib/nc';

const OPEN = '[data-testid="create-credential-dialog"][data-state="open"]';
const SERVICE = '[data-testid="credential-service-row"]';

export default async function () {
    window.dispatchEvent(new CustomEvent('noclick:create-credential'));
    await nc.wait.forElement(OPEN);

    try {
        nc.dom.type(`${OPEN} input`, 'Ashby');
        await nc.wait.until(() =>
            Array.from(document.querySelectorAll(`${OPEN} ${SERVICE}`)).some(
                (row) => /Ashby/.test(row.textContent ?? '')
            )
        );
        const row = Array.from(
            document.querySelectorAll<HTMLElement>(`${OPEN} ${SERVICE}`)
        ).find((candidate) => /Ashby/.test(candidate.textContent ?? ''));
        nc.assert.truthy(row, 'Ashby appears in the credential picker');
        row!.click();

        await nc.wait.until(() =>
            /Connect Ashby/.test(
                document.querySelector(OPEN)?.textContent ?? ''
            )
        );
        await nc.wait.until(() => {
            const button = Array.from(
                document.querySelectorAll<HTMLButtonElement>(`${OPEN} button`)
            ).find((candidate) =>
                /create (new|another)/i.test(candidate.textContent ?? '')
            );
            if (!button) return false;
            button.click();
            return /New Credential/.test(
                document.querySelector(OPEN)?.textContent ?? ''
            );
        });

        const formText = document.querySelector(OPEN)?.textContent ?? '';
        nc.assert.truthy(/API Key/.test(formText), 'API key field is shown');
        nc.assert.truthy(
            !!document.querySelector(`${OPEN} input[type="password"]`),
            'API key is masked'
        );
        return { ok: true };
    } finally {
        document.dispatchEvent(
            new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })
        );
    }
}
