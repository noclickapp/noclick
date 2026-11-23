// @vitest-environment happy-dom
// Leaving the field closes its list a moment later; once the field has gone, nothing it put off is left pending.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ClientProvider } from '@/sdk/client';
import { workFixtureClient } from '@/screens/work/fixtures/client';
import { getInsertReferenceForField } from './DroppableTextField';
import { DynamicOptionsField } from './DynamicOptionsField';
import { formFetch } from './fixtures/world';

beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
});

afterEach(() => {
    cleanup();
    vi.useRealTimers();
});

const CHANNEL = { type: 'string', title: 'Channel', 'x-dynamic-options': { field_name: 'channel', placeholder: 'Pick a channel', searchable: true } };

const field = () =>
    render(
        <ClientProvider client={workFixtureClient(formFetch(), { maxRetries: 0 })}>
            <DynamicOptionsField fieldKey="channel" prop={CHANNEL} value="" onChange={() => undefined} nodeType="example-mail" credentialIds={{}} config={{}} />
        </ClientProvider>
    );

describe('a loaded choice’s timers', () => {
    it('leaves nothing pending once it has gone', () => {
        const view = field();
        const input = screen.getByRole('textbox');
        fireEvent.focus(input);
        fireEvent.blur(input);
        act(() => getInsertReferenceForField('channel')?.('{{ $("a").channel }}'));
        expect(vi.getTimerCount()).toBeGreaterThanOrEqual(2);
        view.unmount();
        expect(vi.getTimerCount()).toBe(0);
        vi.runAllTimers();
    });
});
