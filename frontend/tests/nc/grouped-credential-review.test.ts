// Exercise subset selection across credentials with the actual review component.
// The callback records only local fixture IDs; this test never changes real permissions.
import { createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { MemoryRouter } from 'react-router';
import {
    CredentialRequestReview,
    type UnlockRequest,
} from '~/components/credential/CredentialRequestReview';
import { nc } from '~/lib/nc';

export default async function () {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = createRoot(host);
    const items: UnlockRequest[] = [
        {
            id: 'mail-read',
            credentialId: 'mail',
            credentialName: 'Email',
            account: 'mail@example.test',
            kind: 'unlock',
            title: 'Read',
            summary: '',
            status: 'pending',
        },
        {
            id: 'mail-send',
            credentialId: 'mail',
            credentialName: 'Email',
            account: 'mail@example.test',
            kind: 'unlock',
            title: 'Send',
            summary: '',
            status: 'pending',
        },
        {
            id: 'calendar',
            credentialId: 'calendar',
            credentialName: 'Calendar',
            account: 'calendar@example.test',
            kind: 'unlock',
            title: 'Create',
            summary: '',
            status: 'pending',
        },
    ];
    let approved: string[] = [];
    try {
        flushSync(() =>
            root.render(
                createElement(
                    MemoryRouter,
                    null,
                    createElement(CredentialRequestReview, {
                        mode: 'unlock',
                        requests: items,
                        purpose: 'Review selected tools.',
                        onDecide: (ids: string[]) => {
                            approved = ids;
                        },
                    })
                )
            )
        );
        const boxes =
            host.querySelectorAll<HTMLButtonElement>('[role="checkbox"]');
        nc.assert.equal(
            [...boxes].every(
                (box) => box.getAttribute('aria-checked') === 'true'
            ),
            true,
            'Pending requests start selected'
        );
        nc.assert.equal(
            approved.length,
            0,
            'Opening a request does not approve it'
        );
        flushSync(() => {
            boxes[1].click();
        });
        nc.assert.equal(
            boxes[1].getAttribute('aria-checked'),
            'false',
            'Unselected write tool remains unselected'
        );
        const approve = [...host.querySelectorAll('button')].find(
            (button) => button.textContent === 'Unlock 2 tools'
        )!;
        flushSync(() => approve.click());
        nc.assert.equal(
            approved.join(','),
            'mail-read,calendar',
            'Only selected tools across connections are submitted'
        );
    } finally {
        flushSync(() => root.unmount());
        host.remove();
    }
}
