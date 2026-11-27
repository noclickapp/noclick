// @vitest-environment happy-dom
// A sign-in page that sets Cross-Origin-Opener-Policy cuts its window off from the page that opened it, which from then
// on reads the window as closed while the person is still signing in there. So a closed reading means the person closed
// it only once they're back on the page.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { whenClosed } from './oauthPopup';

describe('whenClosed', () => {
    let signIn: { closed: boolean };
    let onClosed: ReturnType<typeof vi.fn<() => void>>;
    let stop: () => void;
    beforeEach(() => {
        vi.useFakeTimers();
        signIn = { closed: false };
        onClosed = vi.fn();
        stop = whenClosed(signIn as Window, onClosed);
    });
    afterEach(() => {
        stop();
        vi.useRealTimers();
    });

    it('waits while the window only reads closed and the person is away from the page', () => {
        signIn.closed = true;
        vi.advanceTimersByTime(60 * 60_000);
        expect(onClosed).not.toHaveBeenCalled();
    });

    it.each([
        ['the page regains focus', () => window.dispatchEvent(new Event('focus'))],
        ['they click in it', () => window.dispatchEvent(new Event('pointerdown'))],
        ['they type in it', () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'a' }))],
    ])('calls back once the window reads closed and %s', (_, back) => {
        signIn.closed = true;
        back();
        expect(onClosed).toHaveBeenCalledOnce();
        // It stopped watching: nothing more calls back.
        back();
        vi.advanceTimersByTime(5000);
        expect(onClosed).toHaveBeenCalledOnce();
        expect(vi.getTimerCount()).toBe(0);
    });

    it('calls back when the window closes while the person is on the page', () => {
        window.dispatchEvent(new Event('focus'));
        expect(onClosed).not.toHaveBeenCalled();
        signIn.closed = true;
        vi.advanceTimersByTime(500);
        expect(onClosed).toHaveBeenCalledOnce();
    });

    it('waits again once the person goes back to the window', () => {
        window.dispatchEvent(new Event('focus'));
        window.dispatchEvent(new Event('blur'));
        signIn.closed = true;
        vi.advanceTimersByTime(5000);
        expect(onClosed).not.toHaveBeenCalled();
    });

    it('stops watching when told to', () => {
        stop();
        expect(vi.getTimerCount()).toBe(0);
        signIn.closed = true;
        window.dispatchEvent(new Event('focus'));
        expect(onClosed).not.toHaveBeenCalled();
    });
});
