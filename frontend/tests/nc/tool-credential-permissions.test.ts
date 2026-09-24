// Run the workflow tool picker with local route fixtures in the real browser.
// Lock edits must use credential policy submissions without toggling tool exposure;
// no network requests or account permission changes are made by this test.
import { createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AgentToolOperationsPicker } from '~/components/workflow/AgentToolOperationsPicker';
import { nc } from '~/lib/nc';

export default async function () {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = createRoot(host);
    const key = 'automation-gmail.send_email_message';
    let state = {
        id: 'fixture-mail',
        name: 'Fixture Gmail',
        can_edit: true,
        revision: 3,
        approval_operations: ['other-provider.keep'],
        operations: [
            {
                key,
                node_type: 'automation-gmail',
                operation: 'send_email_message',
                display_name: 'Send Email Message',
                description: '',
            },
        ],
    };
    const decisions: unknown[] = [];
    let selectionChanges = 0;
    let finishSave: (() => void) | undefined;
    let loads = 0;
    const router = createMemoryRouter([
        {
            path: '/',
            element: createElement(AgentToolOperationsPicker, {
                nodeType: 'automation-gmail',
                credentialIds: { google: state.id },
                selectedOperations: ['send_email_message'],
                onChange: () => {
                    selectionChanges++;
                },
            }),
        },
        {
            path: '/credential/permissions/:id',
            loader: () => {
                loads++;
                return { state, csrfToken: 'fixture-csrf' };
            },
            action: async ({ request }) => {
                const form = await request.formData();
                nc.assert.equal(
                    form.get('csrf_token'),
                    'fixture-csrf',
                    'Uses authenticated route CSRF'
                );
                const payload = JSON.parse(String(form.get('payload')));
                nc.assert.equal(
                    payload.expected_revision,
                    state.revision,
                    'Uses current policy revision'
                );
                decisions.push(payload);
                await new Promise<void>((resolve) => {
                    finishSave = resolve;
                });
                finishSave = undefined;
                state = {
                    ...state,
                    approval_operations: payload.operations,
                    revision: state.revision + 1,
                };
                return { saved: true };
            },
        },
    ]);
    const lock = () =>
        host.querySelector<HTMLButtonElement>(
            '[aria-label="Require approval for Send Email Message"]'
        );
    try {
        flushSync(() => root.render(createElement(RouterProvider, { router })));
        await nc.wait.until(
            () => !!lock() && lock()!.getAttribute('aria-disabled') !== 'true',
            5000
        );
        nc.assert.equal(
            decisions.length,
            0,
            'Opening the picker changes no rules'
        );
        const originalBounds = lock()!.getBoundingClientRect();
        const originalIcons = [...lock()!.querySelectorAll('svg')];
        const assertStableLayout = () => {
            const bounds = lock()!.getBoundingClientRect();
            nc.assert.deepEqual(
                [bounds.x, bounds.y, bounds.width, bounds.height],
                [
                    originalBounds.x,
                    originalBounds.y,
                    originalBounds.width,
                    originalBounds.height,
                ],
                'The lock and its row do not move during a save or state change'
            );
        };
        lock()!.click();
        await nc.wait.until(
            () => !!finishSave && lock()?.getAttribute('aria-busy') === 'true',
            5000
        );
        assertStableLayout();
        nc.assert.equal(
            lock()!.getAttribute('aria-pressed'),
            'true',
            'Lock transitions before the server responds'
        );
        nc.assert.truthy(
            originalIcons.every(
                (icon, index) => lock()!.querySelectorAll('svg')[index] === icon
            ),
            'Saving does not replace the icons with a spinner'
        );
        finishSave!();
        await nc.wait.until(
            () =>
                lock()?.getAttribute('aria-pressed') === 'true' &&
                lock()?.getAttribute('aria-disabled') !== 'true',
            5000
        );
        assertStableLayout();
        nc.assert.deepEqual(
            state.approval_operations,
            ['other-provider.keep', key],
            'Lock preserves unrelated rules'
        );
        nc.assert.equal(
            selectionChanges,
            0,
            'Lock does not change exposed tools'
        );
        lock()!.click();
        await nc.wait.until(
            () => !!finishSave && lock()?.getAttribute('aria-busy') === 'true',
            5000
        );
        assertStableLayout();
        nc.assert.equal(
            lock()!.getAttribute('aria-pressed'),
            'false',
            'Unlock transitions before the server responds'
        );
        finishSave!();
        await nc.wait.until(
            () =>
                lock()?.getAttribute('aria-pressed') === 'false' &&
                lock()?.getAttribute('aria-disabled') !== 'true',
            5000
        );
        assertStableLayout();
        nc.assert.deepEqual(
            state.approval_operations,
            ['other-provider.keep'],
            'Unlock removes only the named rule'
        );
        nc.assert.equal(
            selectionChanges,
            0,
            'Unlock does not change exposed tools'
        );
        nc.assert.equal(
            router.state.location.pathname,
            '/',
            'Editing stays inline'
        );
        nc.assert.equal(
            loads,
            3,
            'Each save refreshes the policy exactly once'
        );
        return { success: true, decisions: decisions.length };
    } finally {
        finishSave?.();
        flushSync(() => root.unmount());
        router.dispose();
        host.remove();
    }
}
