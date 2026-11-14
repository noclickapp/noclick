// @vitest-environment happy-dom
// The chat composer's "+" menu opens against the composer box, as wide as it. Under StrictMode (the dev server and
// staging) Radix's popper once kept the trigger's discarded first node as the anchor, so the menu measured 0×0 and
// opened in the page's top-left corner with no visible surface.
import { StrictMode, useRef } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('~/hooks/useCachedCredentialList', () => ({ useCredentialList: () => ({ credentials: [], loaded: true }) }));
vi.mock('~/components/shell/connections/accounts', () => ({ useConnectedAccounts: () => [] }));

import { ComposerAddMenu } from '~/components/shell/ComposerAddMenu';

const rect = (x: number, y: number, width: number, height: number) =>
    ({ x, y, width, height, top: y, left: x, right: x + width, bottom: y + height, toJSON: () => ({}) }) as DOMRect;

function Composer() {
    const card = useRef<HTMLDivElement>(null);
    return (
        <div ref={card} data-testid="composer-card">
            <ComposerAddMenu anchorRef={card} side="bottom" onAddFiles={() => {}} onReference={() => {}} />
        </div>
    );
}

afterEach(() => vi.restoreAllMocks());

describe('ComposerAddMenu', () => {
    it('opens against the composer box under StrictMode, however many times it opens', async () => {
        // A node no longer in the page measures 0×0, as a browser reports it.
        vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
            if (!this.isConnected) return rect(0, 0, 0, 0);
            if (this.dataset.testid === 'composer-card') return rect(400, 300, 640, 180);
            if (this.dataset.testid === 'composer-add-button') return rect(410, 430, 36, 36);
            return rect(0, 0, 0, 0);
        });
        render(
            <StrictMode>
                <Composer />
            </StrictMode>
        );
        const plus = screen.getByTestId('composer-add-button');
        for (let i = 0; i < 2; i++) {
            await act(async () => fireEvent.click(plus));
            const wrapper = (await screen.findByTestId('composer-add-menu')).parentElement as HTMLElement;
            await waitFor(() => expect(wrapper.style.getPropertyValue('--radix-popper-anchor-width')).toBe('640px'));
            await act(async () => fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' }));
            await waitFor(() => expect(screen.queryByTestId('composer-add-menu')).toBeNull());
        }
    });
});
