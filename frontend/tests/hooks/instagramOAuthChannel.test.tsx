// @vitest-environment jsdom
// Exercises the real Instagram hook and callback together, including the
// opener-less mobile path and acknowledgement only after credential persistence.
import React from 'react';
import {
    act,
    cleanup,
    render,
    renderHook,
    screen,
    waitFor,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { oauthChannelName } from '~/lib/oauthChannel';

const state = vi.hoisted(() => ({
    data: {} as Record<string, unknown>,
    exchange: vi.fn(),
}));
vi.mock('react-router', async (original) => ({
    ...(await original<typeof import('react-router')>()),
    useLoaderData: () => state.data,
}));
vi.mock('~/hooks/oauth/OAuthExchangeContext', () => ({
    useOAuthExchange: () => state.exchange,
}));
import { useInstagramLoginOAuth } from '~/hooks/oauth/useInstagramLoginOAuth';
import { createOAuthHook } from '~/hooks/oauth/createOAuthHook';
import InstagramCallback from '~/routes/api/auth/instagram.callback';

class TestChannel {
    static peers = new Set<TestChannel>();
    onmessage: ((event: MessageEvent) => void) | null = null;
    closed = false;
    constructor(readonly name: string) {
        TestChannel.peers.add(this);
    }
    postMessage(data: unknown) {
        if (this.closed) throw new Error('closed channel');
        for (const peer of TestChannel.peers) {
            if (peer !== this && peer.name === this.name && !peer.closed) {
                queueMicrotask(() => {
                    if (!peer.closed)
                        peer.onmessage?.(new MessageEvent('message', { data }));
                });
            }
        }
    }
    close() {
        this.closed = true;
        TestChannel.peers.delete(this);
    }
}

function openedAttempt(index = 0): string {
    const url = new URL(
        String(vi.mocked(window.open).mock.calls[index][0]),
        window.location.origin
    );
    expect(url.pathname).toBe('/api/auth/instagram/authorize');
    return url.searchParams.get('callback_channel')!;
}

describe('Instagram callback delivery', () => {
    beforeEach(() => {
        vi.stubGlobal('React', React);
        vi.stubGlobal('BroadcastChannel', TestChannel);
        vi.stubGlobal('opener', null);
        vi.spyOn(window, 'open').mockReturnValue({ closed: true } as Window);
        vi.spyOn(window, 'close').mockImplementation(() => {});
        state.exchange.mockReset();
        state.data = {};
    });
    afterEach(() => {
        cleanup();
        TestChannel.peers.clear();
        vi.useRealTimers();
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    it('finishes with no opener and does not report success before exchange succeeds', async () => {
        let finish!: (value: unknown) => void;
        state.exchange.mockReturnValue(
            new Promise((resolve) => {
                finish = resolve;
            })
        );
        const success = vi.fn();
        const hook = renderHook(() =>
            useInstagramLoginOAuth({ onSuccess: success })
        );
        act(() => hook.result.current.connect('Instagram test'));
        state.data = {
            success: true,
            code: 'synthetic-code',
            redirectUri: 'https://example.com/callback',
            callbackChannel: openedAttempt(),
            scopes: ['instagram_business_basic'],
        };
        render(<InstagramCallback />);
        await waitFor(() => expect(state.exchange).toHaveBeenCalledTimes(1));
        expect(screen.queryByText('Connected Successfully!')).toBeNull();
        expect(state.exchange).toHaveBeenCalledWith(
            expect.objectContaining({
                event_name: 'instagram_login:oauth:exchange',
                code: 'synthetic-code',
                credential_name: 'Instagram test',
            })
        );
        await act(async () => {
            finish({ success: true, credential_id: 'saved-instagram' });
        });
        await waitFor(() =>
            expect(screen.getByText('Connected Successfully!')).toBeTruthy()
        );
        expect(success).toHaveBeenCalledWith(
            expect.objectContaining({ credentialId: 'saved-instagram' })
        );
        expect(TestChannel.peers.size).toBe(0);
    });

    it('reports exchange rejection in both the parent and callback', async () => {
        state.exchange.mockResolvedValue({
            success: false,
            error: 'Instagram account is not eligible',
        });
        const hook = renderHook(() => useInstagramLoginOAuth());
        act(() => hook.result.current.connect('Instagram test'));
        state.data = {
            success: true,
            code: 'synthetic-code',
            callbackChannel: openedAttempt(),
        };
        render(<InstagramCallback />);
        await waitFor(() =>
            expect(
                screen.getByText('Instagram account is not eligible')
            ).toBeTruthy()
        );
        expect(hook.result.current.error).toBe(
            'Instagram account is not eligible'
        );
        expect(screen.queryByText('Connected Successfully!')).toBeNull();
    });

    it('isolates simultaneous forms and rejects duplicate callback delivery', async () => {
        state.exchange.mockResolvedValue({
            success: true,
            credential_id: 'saved-instagram',
        });
        const firstSuccess = vi.fn();
        const secondSuccess = vi.fn();
        const first = renderHook(() =>
            useInstagramLoginOAuth({ onSuccess: firstSuccess })
        );
        const second = renderHook(() =>
            useInstagramLoginOAuth({ onSuccess: secondSuccess })
        );
        act(() => {
            first.result.current.connect('first');
            second.result.current.connect('second');
        });
        expect(openedAttempt(0)).not.toBe(openedAttempt(1));
        expect(vi.mocked(window.open).mock.calls[0][1]).not.toBe(
            vi.mocked(window.open).mock.calls[1][1]
        );
        const sender = new TestChannel(
            oauthChannelName('instagram_login', openedAttempt(1))
        );
        await act(async () => {
            sender.postMessage({
                type: 'instagram_login-oauth-callback',
                success: true,
                code: 'synthetic-code',
            });
            sender.postMessage({
                type: 'instagram_login-oauth-callback',
                success: true,
                code: 'synthetic-code',
            });
        });
        await waitFor(() => expect(secondSuccess).toHaveBeenCalledTimes(1));
        expect(firstSuccess).not.toHaveBeenCalled();
        expect(state.exchange).toHaveBeenCalledTimes(1);
        expect(state.exchange).toHaveBeenCalledWith(
            expect.objectContaining({ credential_name: 'second' })
        );
        sender.close();
    });

    it('does not cancel on COOP-detached popup.closed; still times out and cleans up', async () => {
        vi.useFakeTimers();
        const hook = renderHook(() => useInstagramLoginOAuth());
        act(() => hook.result.current.connect('Instagram test'));
        await act(async () => {
            vi.advanceTimersByTime(2000);
        });
        expect(hook.result.current.isConnecting).toBe(true);
        expect(TestChannel.peers.size).toBe(1);
        await act(async () => {
            vi.advanceTimersByTime(5 * 60_000);
        });
        expect(hook.result.current.error).toContain('timed out');
        expect(TestChannel.peers.size).toBe(0);
    });

    it('cleans up when popups are blocked and when the form unmounts', () => {
        vi.useFakeTimers();
        vi.mocked(window.open).mockReturnValueOnce(null);
        const hook = renderHook(() => useInstagramLoginOAuth());
        act(() => hook.result.current.connect('Instagram test'));
        expect(hook.result.current.error).toContain('Popup was blocked');
        expect(TestChannel.peers.size).toBe(0);
        act(() => hook.result.current.connect('Instagram test'));
        expect(TestChannel.peers.size).toBe(1);
        hook.unmount();
        expect(TestChannel.peers.size).toBe(0);
        expect(vi.getTimerCount()).toBe(0);
    });

    it('replaces a cancelled pending attempt when the shared form retries', async () => {
        vi.useFakeTimers();
        state.exchange.mockResolvedValue({
            success: true,
            credential_id: 'saved-retry',
        });
        const success = vi.fn();
        const hook = renderHook(() =>
            useInstagramLoginOAuth({ onSuccess: success })
        );
        act(() => hook.result.current.connect('cancelled'));
        const previousChannel = [...TestChannel.peers][0];
        const previousCallback = previousChannel.onmessage!;
        await act(async () => {
            vi.advanceTimersByTime(4 * 60_000);
        });
        // Cancel clears the shared form's state, without unmounting the hook
        // or receiving a provider callback. The next click starts a new attempt.
        act(() => hook.result.current.connect('retry'));
        expect(window.open).toHaveBeenCalledTimes(2);
        expect(openedAttempt(0)).not.toBe(openedAttempt(1));
        expect(vi.mocked(window.open).mock.calls[0][1]).not.toBe(
            vi.mocked(window.open).mock.calls[1][1]
        );
        expect(previousChannel.closed).toBe(true);
        expect(TestChannel.peers.size).toBe(1);
        expect(vi.getTimerCount()).toBe(1);
        await act(async () => {
            // Even an already-queued message from the cancelled channel is stale.
            previousCallback(
                new MessageEvent('message', {
                    data: {
                        type: 'instagram_login-oauth-callback',
                        success: true,
                        code: 'cancelled-code',
                    },
                })
            );
            vi.advanceTimersByTime(61_000);
        });
        expect(state.exchange).not.toHaveBeenCalled();
        expect(hook.result.current.isConnecting).toBe(true);
        const sender = new TestChannel(
            oauthChannelName('instagram_login', openedAttempt(1))
        );
        await act(async () => {
            sender.postMessage({
                type: 'instagram_login-oauth-callback',
                success: true,
                code: 'retry-code',
            });
        });
        expect(state.exchange).toHaveBeenCalledTimes(1);
        expect(state.exchange).toHaveBeenCalledWith(
            expect.objectContaining({
                code: 'retry-code',
                credential_name: 'retry',
            })
        );
        expect(success).toHaveBeenCalledTimes(1);
        expect(vi.getTimerCount()).toBe(0);
        sender.close();
        expect(TestChannel.peers.size).toBe(0);
    });

    it('does not replace an attempt while its credential exchange is in flight', async () => {
        let finish!: (value: unknown) => void;
        state.exchange.mockReturnValue(
            new Promise((resolve) => {
                finish = resolve;
            })
        );
        const hook = renderHook(() => useInstagramLoginOAuth());
        act(() => hook.result.current.connect('persisting'));
        const sender = new TestChannel(
            oauthChannelName('instagram_login', openedAttempt())
        );
        await act(async () => {
            sender.postMessage({
                type: 'instagram_login-oauth-callback',
                success: true,
                code: 'synthetic-code',
            });
        });
        act(() => hook.result.current.connect('retry'));
        expect(window.open).toHaveBeenCalledTimes(1);
        expect(state.exchange).toHaveBeenCalledTimes(1);
        await act(async () => {
            finish({ success: true, credential_id: 'saved' });
        });
        act(() => hook.result.current.connect('next'));
        expect(window.open).toHaveBeenCalledTimes(2);
        sender.close();
    });

    it('does not let the previous attempt watchdog cancel a retry', async () => {
        vi.useFakeTimers();
        const hook = renderHook(() => useInstagramLoginOAuth());
        act(() => hook.result.current.connect('first'));
        await act(async () => {
            vi.advanceTimersByTime(4 * 60_000);
        });
        const sender = new TestChannel(
            oauthChannelName('instagram_login', openedAttempt())
        );
        await act(async () => {
            sender.postMessage({
                type: 'instagram_login-oauth-callback',
                success: false,
                error: 'Declined',
            });
        });
        sender.close();
        expect(vi.getTimerCount()).toBe(0);
        act(() => hook.result.current.connect('retry'));
        await act(async () => {
            vi.advanceTimersByTime(2 * 60_000);
        });
        expect(hook.result.current.isConnecting).toBe(true);
        expect(hook.result.current.error).toBeNull();
    });

    it('preserves same-origin postMessage for providers that do not use the channel', async () => {
        const useLegacyHook = createOAuthHook({ provider: 'linear' });
        const success = vi.fn();
        state.exchange.mockResolvedValue({
            success: true,
            credential_id: 'saved-linear',
        });
        const hook = renderHook(() => useLegacyHook({ onSuccess: success }));
        act(() => hook.result.current.connect('Linear test'));
        const data = {
            type: 'linear-oauth-callback',
            success: true,
            code: 'synthetic-code',
        };
        await act(async () => {
            window.dispatchEvent(
                new MessageEvent('message', {
                    origin: 'https://untrusted.example',
                    data,
                })
            );
        });
        expect(state.exchange).not.toHaveBeenCalled();
        await act(async () => {
            window.dispatchEvent(
                new MessageEvent('message', {
                    origin: window.location.origin,
                    data,
                })
            );
        });
        expect(success).toHaveBeenCalledTimes(1);
        expect(state.exchange).toHaveBeenCalledWith(
            expect.objectContaining({ event_name: 'linear:oauth:exchange' })
        );
        expect(TestChannel.peers.size).toBe(0);
    });
});
