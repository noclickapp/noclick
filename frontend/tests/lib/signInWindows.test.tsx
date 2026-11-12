// @vitest-environment happy-dom
//
// Every sign-in and connect window opens inside the click that asks for it, through lib/oauthPopup.ts. A window opened
// after an await (a start call, a lookup) is a pop-up nobody asked for by the time it opens, and browsers block it:
// Sign in with Claude and Sign in with ChatGPT on a connect link opened nothing (2026-11-12).
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, renderHook, screen } from '@testing-library/react';
import { OAuthExchangeProvider, type OAuthExchange } from '~/hooks/oauth/OAuthExchangeContext';
import { useOAuthConnect } from '~/hooks/useOAuthConnect';
import { getAllProviderKeys, getProviderConfig } from '~/utils/oauthProviders';
import { INTEGRATION_METADATA } from '~/utils/integrationMetadata';
import { CodexDeviceCodeAuth } from '~/components/workflow/CodexDeviceCodeAuth';
import { holdSignInWindow, openTabForLater } from '~/lib/oauthPopup';

const APP = join(dirname(fileURLToPath(import.meta.url)), '../../app');

// Each file that may call window.open without the helper, and why. Only a window that is no sign-in or connect.
const ALLOWED: Record<string, string> = {
    'lib/oauthPopup.ts': 'The helper: every sign-in and connect window opens here.',
    'components/shell/AppSidebar.tsx': 'The account menu opens the Discord community on a click; no sign-in.',
    'components/chat/drawer/ChatSlashOptions.tsx': 'The /community command opens the Discord community on a click; no sign-in.',
    'components/nav/NavBar.tsx': "The open edition's nav opens the Discord community on a click; no sign-in.",
    'cloud/components/coordinator/atWork/pieces.tsx': "Opens a row's published site on a click; no sign-in.",
    'routes/api/auth/shopify.app.tsx': "Shopify App Bridge's top-level navigation inside Shopify admin (target _top), not a new window.",
};

const OPENS = /\b(?:window|globalThis|self)\s*\.\s*open\s*\(/;
// Tests stub windows; design labs are local mock-ups that ship to no one.
const SKIPPED = (path: string) => /\.(test|spec)\.[jt]sx?$/.test(path) || /(^|\/)components\/design\//.test(path) || /-lab[.$]/.test(path);

function sources(dir: string): string[] {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
        const path = join(dir, entry.name);
        if (entry.isDirectory()) return entry.name === 'node_modules' ? [] : sources(path);
        return /\.[jt]sx?$/.test(entry.name) ? [path] : [];
    });
}

describe('sign-in windows open through the one helper', () => {
    it('no shipped or hosted code calls window.open outside lib/oauthPopup.ts', () => {
        const strays = sources(APP).flatMap((path) => {
            const rel = relative(APP, path).split('\\').join('/');
            if (SKIPPED(rel) || rel in ALLOWED) return [];
            return readFileSync(path, 'utf8')
                .split('\n')
                .flatMap((line, i) => (OPENS.test(line) ? [`app/${rel}:${i + 1}: ${line.trim()}`] : []));
        });
        expect(strays, 'Open the window with openTabForLater (lib/oauthPopup.ts) in the click, or allow the file here with why it opens no sign-in').toEqual([]);
    });
});

afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
});

interface FakeWindow {
    closed: boolean;
    name: string;
    opener: unknown;
    location: { href: string };
    close: () => void;
    focus: () => void;
}
const fakeWindow = (): FakeWindow => {
    const w: FakeWindow = { closed: false, name: '', opener: window, location: { href: 'about:blank' }, close: vi.fn(() => (w.closed = true)), focus: vi.fn() };
    return w;
};
const spyOpen = () => {
    const opened: FakeWindow[] = [];
    const open = vi.spyOn(window, 'open').mockImplementation(() => {
        const w = fakeWindow();
        opened.push(w);
        return w as unknown as Window;
    });
    return { open, opened };
};
const pending = <T,>() => {
    let resolve!: (value: T) => void;
    const promise = new Promise<T>((r) => (resolve = r));
    return { promise, resolve };
};

describe('every OAuth integration', () => {
    it('opens its sign-in window inside the click, before anything it awaits', () => {
        // The exchange never answers: a window opened only once something resolves never opens here.
        const never: OAuthExchange = () => new Promise(() => {});
        const wrapper = ({ children }: { children: ReactNode }) => <OAuthExchangeProvider value={never}>{children}</OAuthExchangeProvider>;
        const { result } = renderHook(() => useOAuthConnect(), { wrapper });
        // A popup that POSTs its setup values (Slack, Shopify, QuickBooks) submits a form into it.
        vi.spyOn(HTMLFormElement.prototype, 'submit').mockImplementation(() => {});
        const providers = [...new Set(getAllProviderKeys().map((key) => getProviderConfig(key)?.oauthProvider).filter((p): p is string => !!p))];
        expect(providers.length).toBeGreaterThan(40);
        const silent: string[] = [];
        for (const provider of providers) {
            const { open } = spyOpen();
            const tenant = getProviderConfig(provider)?.connectInput;
            act(() => {
                result.current.connect(
                    provider,
                    `${provider} account`,
                    undefined,
                    tenant && tenant.kind !== 'site' ? 'acme' : undefined,
                    tenant?.kind === 'site' ? 'acme' : undefined
                );
            });
            if (open.mock.calls.length !== 1) silent.push(`${provider}: ${open.mock.calls.length} windows`);
            open.mockRestore();
        }
        expect(silent).toEqual([]);
        // Declared integrations (the generic hook) are among them.
        expect(providers).toEqual(expect.arrayContaining(Object.keys(INTEGRATION_METADATA.oauthProviders)));
    });
});

describe("ChatGPT's device-code sign-in", () => {
    const started = { success: true, verification_url: 'https://auth.openai.com/codex/device', user_code: 'AVJE-VI605', device_auth_id: 'dev-1', interval: 5 };

    function clipboard() {
        const written: string[] = [];
        class Item {
            constructor(readonly data: Record<string, Promise<Blob>>) {}
        }
        vi.stubGlobal('ClipboardItem', Item);
        Object.defineProperty(navigator, 'clipboard', {
            configurable: true,
            value: {
                write: vi.fn(async ([item]: Item[]) => {
                    written.push(await (await item.data['text/plain']).text());
                }),
                writeText: vi.fn(async (text: string) => void written.push(text)),
            },
        });
        return written;
    }

    it('opens the page in the click, points it once the start answers, and copies the code', async () => {
        const written = clipboard();
        const { open, opened } = spyOpen();
        const start = pending<typeof started>();
        const sendEvent = vi.fn((event: { event_name: string }) => (event.event_name === 'codex:auth:start' ? start.promise : new Promise(() => {})));
        render(<CodexDeviceCodeAuth credentialIds={{}} onCredentialIdsChange={() => {}} onCredentialCreated={async () => {}} sendEvent={sendEvent} />);

        fireEvent.click(screen.getByRole('button', { name: /Connect with ChatGPT account/ }));
        // Opened before the server answered: a tab opened after the await is a blocked pop-up.
        expect(open).toHaveBeenCalledTimes(1);
        expect(open).toHaveBeenCalledWith('about:blank', '_blank');
        expect(opened[0].opener).toBeNull();
        // The clipboard write started in the click too, holding the code to come.
        expect(navigator.clipboard.write).toHaveBeenCalledTimes(1);

        await act(async () => start.resolve(started));
        expect(opened[0].location.href).toBe('https://auth.openai.com/codex/device');
        expect(await screen.findByText('AVJE-VI605')).toBeTruthy();
        expect(await screen.findByText('Code copied')).toBeTruthy();
        expect(written).toEqual(['AVJE-VI605']);
        expect(open).toHaveBeenCalledTimes(1);
    });

    it('closes the window when the sign-in cannot start, and copies nothing', async () => {
        const written = clipboard();
        const { opened } = spyOpen();
        const sendEvent = vi.fn(async () => ({ success: false, message: 'Device code login is off for this account' }));
        render(<CodexDeviceCodeAuth credentialIds={{}} onCredentialIdsChange={() => {}} onCredentialCreated={async () => {}} sendEvent={sendEvent} />);

        fireEvent.click(screen.getByRole('button', { name: /Connect with ChatGPT account/ }));
        expect(await screen.findByText('Device code login is off for this account')).toBeTruthy();
        expect(opened[0].close).toHaveBeenCalled();
        expect(written).toEqual([]);
    });

    it('offers the code to copy where the browser would not take it unasked', async () => {
        Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn(async () => {}) } });
        vi.stubGlobal('ClipboardItem', undefined);
        (navigator.clipboard.writeText as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('Document is not focused.'));
        spyOpen();
        render(<CodexDeviceCodeAuth credentialIds={{}} onCredentialIdsChange={() => {}} onCredentialCreated={async () => {}} sendEvent={async () => started} />);

        fireEvent.click(screen.getByRole('button', { name: /Connect with ChatGPT account/ }));
        fireEvent.click(await screen.findByRole('button', { name: 'Copy code' }));
        expect(await screen.findByText('Code copied')).toBeTruthy();
        expect(navigator.clipboard.writeText).toHaveBeenLastCalledWith('AVJE-VI605');
    });
});

describe('a window held for a sign-in named after an await', () => {
    it('is the window the sign-in opens, renamed for its callback, and is closed if no sign-in takes it', () => {
        const { open, opened } = spyOpen();
        const release = holdSignInWindow();
        expect(open).toHaveBeenCalledTimes(1);
        const signIn = openTabForLater({ url: '/api/auth/google/authorize?x=1', name: 'google-oauth', popup: { width: 500, height: 600 } });
        expect(open).toHaveBeenCalledTimes(1);
        expect(signIn.window).toBe(opened[0]);
        expect(opened[0].name).toBe('google-oauth');
        expect(opened[0].location.href).toBe('/api/auth/google/authorize?x=1');
        release();
        expect(opened[0].close).not.toHaveBeenCalled();

        const unused = holdSignInWindow();
        unused();
        expect(opened[1].close).toHaveBeenCalled();
    });
});
