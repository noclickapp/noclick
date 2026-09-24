// Exercise the actual credential permission editor in the browser stylesheet.
// Isolated data keeps this test from changing any account's security policy.
import { createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { MemoryRouter } from 'react-router';
import { CredentialPermissions } from '~/components/credential/CredentialPermissions';
import { nc } from '~/lib/nc';

export default async function () {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = createRoot(host);
    let saved: string[] | undefined;
    try {
        flushSync(() =>
            root.render(
                createElement(
                    MemoryRouter,
                    null,
                    createElement(CredentialPermissions, {
                        state: {
                            id: 'local-ui-test',
                            name: 'Personal email',
                            revision: 1,
                            can_edit: true,
                            approval_operations: ['gmail.send'],
                            operations: [
                                {
                                    key: 'gmail.send',
                                    node_type: 'automation-gmail',
                                    display_name: 'Send email',
                                    description: '',
                                },
                                {
                                    key: 'gmail.read',
                                    node_type: 'automation-gmail',
                                    display_name: 'Read email',
                                    description: '',
                                },
                            ],
                        },
                        onSave: (operations: string[]) => {
                            saved = operations;
                        },
                    })
                )
            )
        );
        const read = host.querySelector<HTMLButtonElement>(
            '[aria-label="Require approval for Read email"]'
        )!;
        flushSync(() => read.click());
        nc.assert.equal(
            read.getAttribute('aria-pressed'),
            'true',
            'Selected action requires approval'
        );
        nc.assert.falsy(
            saved,
            'Changing a lock does not persist a security policy'
        );
        const save = [...host.querySelectorAll('button')].find(
            (button) => button.textContent === 'Save rules'
        )!;
        flushSync(() => save.click());
        nc.assert.equal(
            saved?.join(','),
            'gmail.send,gmail.read',
            'Save preserves existing restrictions'
        );
        const preset = (label: string) =>
            [...host.querySelectorAll('button')].find(
                (button) => button.textContent === label
            )!;
        saved = undefined;
        flushSync(() => preset('Read-only').click());
        nc.assert.equal(
            read.getAttribute('aria-pressed'),
            'false',
            'Read-only leaves read actions free'
        );
        nc.assert.truthy(
            host.textContent?.includes('Approval required'),
            'Changes visibly require approval'
        );
        nc.assert.truthy(
            host.textContent?.includes('Unlocked'),
            'Unrestricted actions are explicit'
        );
        nc.assert.falsy(
            host.querySelector('[role="switch"]'),
            'Permission controls never resemble an enable switch'
        );
        nc.assert.falsy(saved, 'Shortcuts require an explicit save');
        flushSync(() => preset('None').click());
        nc.assert.equal(
            read.getAttribute('aria-pressed'),
            'true',
            'None locks all calls'
        );
        nc.assert.truthy(
            read.disabled,
            'The wildcard also covers future actions'
        );
        flushSync(() => preset('All').click());
        nc.assert.equal(
            read.getAttribute('aria-pressed'),
            'false',
            'All removes locks'
        );
        nc.assert.truthy(
            host.textContent?.includes('Only you can remove'),
            'The human-only unlock boundary is visible'
        );
    } finally {
        flushSync(() => root.unmount());
        host.remove();
    }
}
