// @vitest-environment happy-dom
// The shell drawer says why a shell closed, in the server's words when it gave some (an own computer whose NoClick
// agent is too old for shells, a machine that didn't answer), else that the shell ended or the connection dropped.
// The real terminal connection runs over a stand-in websocket; xterm.js, which needs a real browser, is a stand-in too.
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
    TERMINAL_CLOSED_FOR_GOOD,
    TerminalConnection,
} from 'noclick';
import { ShellDrawer, type OpenedShell } from './ShellDrawer';

vi.mock('@xterm/xterm', () => ({
    Terminal: class {
        cols = 80;
        rows = 24;
        options = {};
        loadAddon() {}
        open() {}
        focus() {}
        write() {}
        onData() {}
        onResize() {}
        dispose() {}
    },
}));
vi.mock('@xterm/addon-fit', () => ({
    FitAddon: class {
        fit() {}
    },
}));

/** The terminal websocket as the browser sees it: the test plays the server's side. */
class FakeSocket {
    static all: FakeSocket[] = [];
    binaryType = 'blob';
    sent: unknown[] = [];
    onopen: (() => void) | null = null;
    onmessage: ((event: { data: unknown }) => void) | null = null;
    onclose: ((event: { code: number; reason: string }) => void) | null = null;
    constructor(readonly url: string) {
        FakeSocket.all.push(this);
    }
    send(data: unknown) {
        this.sent.push(data);
    }
    close() {}
    /** The server ends it with a close frame. */
    closes(code: number, reason = '') {
        this.onclose?.({ code, reason });
    }
}

const opened = (): OpenedShell => {
    const token = `tok-${FakeSocket.all.length}`;
    return {
        token,
        connect: (options = {}) =>
            new TerminalConnection('wss://terminal.test/shell', token, options),
    };
};

beforeEach(() => {
    FakeSocket.all = [];
    vi.stubGlobal('WebSocket', FakeSocket);
    if (!document.fonts)
        Object.defineProperty(document, 'fonts', {
            value: { ready: Promise.resolve() },
            configurable: true,
        });
});
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

async function drawer() {
    const open = vi.fn(async () => opened());
    render(
        <ShellDrawer
            label="Your shell on ops-box"
            running
            open={open}
            asleep="ops-box is offline."
            onClose={() => undefined}
        />
    );
    await vi.waitFor(() => expect(FakeSocket.all).toHaveLength(1));
    const socket = FakeSocket.all[0];
    socket.onopen?.();
    return { open, socket };
}

const said = () => screen.getByTestId('shell-drawer').textContent;

describe('a shell that closes', () => {
    it('says the server’s reason: an own computer whose NoClick agent is too old for shells', async () => {
        const { open, socket } = await drawer();
        socket.closes(
            TERMINAL_CLOSED_FOR_GOOD.ended,
            'ops-box runs an older NoClick agent; it updates itself once idle'
        );
        await vi.waitFor(() =>
            expect(said()).toContain(
                'ops-box runs an older NoClick agent; it updates itself once idle'
            )
        );
        expect(said()).not.toContain('The shell ended.');
        expect(screen.queryByTestId('live-terminal')).toBeNull();

        fireEvent.click(screen.getByRole('button', { name: 'Open another' }));
        await vi.waitFor(() => expect(open).toHaveBeenCalledTimes(2));
        await vi.waitFor(() => expect(FakeSocket.all).toHaveLength(2));
    });

    it('says a refusal that isn’t final in the server’s words too', async () => {
        const { socket } = await drawer();
        socket.closes(
            1011,
            'The terminal didn’t open (ops-box didn’t answer); open it again.'
        );
        await vi.waitFor(() =>
            expect(said()).toContain('ops-box didn’t answer')
        );
        expect(said()).not.toContain('The connection dropped.');
    });

    it('says the shell ended when bash exits', async () => {
        const { socket } = await drawer();
        socket.onmessage?.({
            data: JSON.stringify({ type: 'ready', state: 'open' }),
        });
        socket.closes(TERMINAL_CLOSED_FOR_GOOD.ended);
        await vi.waitFor(() => expect(said()).toContain('The shell ended.'));
    });

    it('says the connection dropped when it went with no reason', async () => {
        const { socket } = await drawer();
        socket.closes(1006);
        await vi.waitFor(() =>
            expect(said()).toContain('The connection dropped.')
        );
        expect(
            screen.getByRole('button', { name: 'Open another' })
        ).toBeTruthy();
    });
});
