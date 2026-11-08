// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useGenericDeviceOAuth } from '~/hooks/oauth/useGenericDeviceOAuth';
const exchange = vi.hoisted(() => vi.fn());
vi.mock('~/hooks/oauth/OAuthExchangeContext', () => ({
    useOAuthExchange: () => exchange,
}));
afterEach(() => {
    vi.useRealTimers();
    vi.resetAllMocks();
});
const started = {
    success: true,
    authorization_id: 'opaque',
    user_code: 'ABCD',
    verification_uri: 'https://provider.example/activate',
    interval: 5,
    expires_in: 60,
};

it('polls at the returned interval, handles slow_down and completes through the shared transport', async () => {
    vi.useFakeTimers();
    exchange
        .mockResolvedValueOnce(started)
        .mockResolvedValueOnce({
            success: true,
            status: 'slow_down',
            interval: 10,
        })
        .mockResolvedValueOnce({
            success: true,
            status: 'completed',
            credential_id: 'credential',
            name: 'Account',
        });
    const onSuccess = vi.fn();
    const { result } = renderHook(() => useGenericDeviceOAuth({ onSuccess }));
    await act(async () =>
        result.current.connect('example', ['read'], { tenant: 'company' })
    );
    expect(result.current.authorization).toMatchObject({
        userCode: 'ABCD',
        verificationUrl: started.verification_uri,
    });
    expect(exchange.mock.calls[0][0]).toEqual({
        event_name: 'oauth:device:start',
        provider: 'example',
        scopes: ['read'],
        context: { tenant: 'company' },
    });
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(exchange).toHaveBeenCalledTimes(2);
    await act(async () => vi.advanceTimersByTimeAsync(9999));
    expect(exchange).toHaveBeenCalledTimes(2);
    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(onSuccess).toHaveBeenCalledWith(
        expect.objectContaining({
            provider: 'example',
            credentialId: 'credential',
        })
    );
    expect(result.current.isConnecting).toBe(false);
    expect(result.current.authorization).toBeNull();
    expect(exchange.mock.calls[1][0]).toEqual({
        event_name: 'oauth:device:poll',
        provider: 'example',
        authorization_id: 'opaque',
    });
});

it.each(['expired', 'denied', 'error'])(
    'ends a %s flow with an error',
    async (status) => {
        vi.useFakeTimers();
        exchange
            .mockResolvedValueOnce(started)
            .mockResolvedValueOnce({ success: status !== 'error', status });
        const onError = vi.fn();
        const { result } = renderHook(() => useGenericDeviceOAuth({ onError }));
        await act(async () => result.current.connect('example', [], {}));
        await act(async () => vi.advanceTimersByTimeAsync(5000));
        expect(onError).toHaveBeenCalledOnce();
        expect(result.current.isConnecting).toBe(false);
        await act(async () => vi.advanceTimersByTimeAsync(60000));
        expect(exchange).toHaveBeenCalledTimes(2);
    }
);

it('cancels polling on unmount and ignores a late start reply', async () => {
    vi.useFakeTimers();
    let resolve: (value: unknown) => void = () => {};
    exchange.mockReturnValue(
        new Promise((done) => {
            resolve = done;
        })
    );
    const onSuccess = vi.fn();
    const { result, unmount } = renderHook(() =>
        useGenericDeviceOAuth({ onSuccess })
    );
    let pending: Promise<void>;
    act(() => {
        pending = result.current.connect('example', [], {});
    });
    unmount();
    await act(async () => {
        resolve(started);
        await pending;
        vi.advanceTimersByTime(60000);
    });
    expect(exchange).toHaveBeenCalledTimes(1);
    expect(onSuccess).not.toHaveBeenCalled();
});
