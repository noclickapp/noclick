// Exercise the actual Claude sign-in component without sending a provider request.
// The fixture owns a separate DOM root and removes it when the check finishes.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { ClaudeCodeOAuth } from '~/components/workflow/ClaudeCodeOAuth';
import { nc } from '~/lib/nc';

export default async function () {
    const host = document.createElement('div');
    host.id = 'nc-claude-recovery';
    document.body.appendChild(host);
    const root = createRoot(host);
    const originalOpen = window.open;
    const requests: Record<string, unknown>[] = [];
    window.open = () => null;
    const send = async (request: Record<string, unknown>) => {
        requests.push(request);
        if (request.event_name === 'claude-code:auth:start') {
            return {
                success: true,
                auth_url: 'https://example.test/auth',
                auth_session_id: `session-${requests.length}`,
            };
        }
        return {
            success: false,
            message:
                'This authorization was already used. Start a fresh sign-in.',
        };
    };
    const clickButton = async (text: string) => {
        const button = Array.from(host.querySelectorAll('button')).find(
            (b) => b.textContent?.trim() === text
        );
        nc.assert.ok(button, `Button ${text} should exist`);
        button!.click();
        await nc.wait.ms(40);
    };
    try {
        flushSync(() =>
            root.render(
                React.createElement(ClaudeCodeOAuth, {
                    credentialIds: {},
                    onCredentialIdsChange: () => {},
                    onCredentialCreated: async () => {},
                    sendEvent: send,
                })
            )
        );
        await clickButton('Connect with Claude account');
        await nc.wait.forElement('#nc-claude-recovery input');
        nc.dom.type('#nc-claude-recovery input', 'already-used-code');
        await nc.wait.ms(40);
        await clickButton('Confirm Token');
        nc.assert.ok(
            host.textContent?.includes('already used'),
            'Actual failure must be visible'
        );
        nc.assert.equal(
            host.querySelector('input'),
            null,
            'Consumed authorization form must disappear'
        );
        await clickButton('Try again');
        await clickButton('Connect with Claude account');
        await nc.wait.forElement('#nc-claude-recovery input');
        nc.assert.equal(
            host.querySelector<HTMLInputElement>('input')!.value,
            '',
            'Fresh authorization must clear the old code'
        );
        nc.assert.equal(
            requests.length,
            3,
            'One exchange followed by a fresh start'
        );
        return { success: true, exchanges: 1, starts: 2 };
    } finally {
        root.unmount();
        host.remove();
        window.open = originalOpen;
    }
}
