// @vitest-environment jsdom
// The country picker's rows: a long detail (the kinds of number sold there) sits on a line of its own under the name,
// both truncating, so the name never shrinks to nothing beside it and the list never scrolls sideways; a short one (a
// calling code) can sit beside the name, which truncates while it doesn't. The list wears the app's scrollbar.
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { CountryPicker } from '~/components/ui/country-picker';

const LONG = 'Local, Mobile, Toll-free, Shared cost · National needs documents';

beforeAll(() => {
    // Radix measures what it positions.
    globalThis.ResizeObserver ??= class {
        observe() {}
        unobserve() {}
        disconnect() {}
    } as unknown as typeof ResizeObserver;
});
afterEach(cleanup);

function open(props: Partial<Parameters<typeof CountryPicker>[0]> = {}) {
    const onPick = vi.fn();
    render(
        <CountryPicker
            value="AR"
            options={[
                { code: 'AR', detail: LONG },
                { code: 'AO', detail: 'Local' },
                { code: 'GB', detail: 'Local, Mobile' },
            ]}
            onPick={onPick}
            trigger={<button type="button">Country</button>}
            {...props}
        />
    );
    fireEvent.click(screen.getByRole('button', { name: 'Country' }));
    return { list: screen.getByRole('listbox'), onPick };
}

const classes = (el: Element | null) => (el?.getAttribute('class') ?? '').split(/\s+/);

it('puts a long detail on its own line under the name, both truncating, with the flag and check kept', () => {
    const { list, onPick } = open();
    expect(classes(list)).toEqual(expect.arrayContaining(['scrollbar-subtle', 'overflow-y-auto', 'overflow-x-hidden']));
    const argentina = within(list).getByRole('option', { name: /Argentina/ });
    const name = within(argentina).getByText('Argentina');
    const detail = within(argentina).getByText(LONG);
    // Two lines in one column that may shrink: neither can push the other out.
    expect(name.parentElement).toBe(detail.parentElement);
    expect(classes(name.parentElement)).toEqual(expect.arrayContaining(['min-w-0', 'flex-1']));
    expect(classes(name)).toEqual(expect.arrayContaining(['block', 'truncate']));
    expect(classes(detail)).toEqual(expect.arrayContaining(['block', 'truncate', 'text-muted-foreground']));
    expect(classes(detail)).not.toContain('shrink-0');
    // The flag and the check hold their size beside it.
    const [flag] = Array.from(argentina.querySelectorAll('svg'));
    expect(classes(flag)).toContain('shrink-0');
    expect(classes(argentina.lastElementChild)).toContain('shrink-0');
    // Every row reads the same way, whatever its detail.
    expect(within(list).getByRole('option', { name: /Angola/ }).textContent).toBe('AngolaLocal');
    fireEvent.click(within(list).getByRole('option', { name: /United Kingdom/ }));
    expect(onPick).toHaveBeenCalledWith('GB');
});

it('keeps a short detail beside the name, where the name truncates and the detail does not', () => {
    const { list } = open({ detailBeside: true, options: [{ code: 'GB', detail: '+44' }], value: 'GB' });
    const row = within(list).getByRole('option', { name: /United Kingdom/ });
    const name = within(row).getByText('United Kingdom');
    const code = within(row).getByText('+44');
    expect(name.parentElement).toBe(row);
    expect(code.parentElement).toBe(row);
    expect(classes(name)).toEqual(expect.arrayContaining(['min-w-0', 'flex-1', 'truncate']));
    expect(classes(code)).toContain('shrink-0');
});
