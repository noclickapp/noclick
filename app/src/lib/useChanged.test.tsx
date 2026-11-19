// @vitest-environment happy-dom
// State a component starts over for each item is put down while the next item renders. Put down in an effect instead,
// it undoes a click that lands after the page is drawn and before its effects run: React runs them a task later when
// the render wasn't a click's (here, an update from outside any event, as a navigation's or a read's is).
import { useEffect, useState } from 'react';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { clickAsDrawn } from './clickAsDrawn';
import { useChanged } from './useChanged';

afterEach(cleanup);

function Picker({ id, reset }: { id: string; reset: 'render' | 'effect' }) {
    const [picked, setPicked] = useState<string | null>(null);
    const changed = useChanged(id);
    if (reset === 'render' && changed) setPicked(null);
    useEffect(() => {
        if (reset === 'effect') setPicked(null);
    }, [id, reset]);
    return (
        <div>
            <button type="button" onClick={() => setPicked(id)}>
                Pick {id}
            </button>
            <p data-testid="picked">{picked ?? 'none'}</p>
        </div>
    );
}

/** Shows the picker for whichever id `show` was last given, from outside any event. */
function host(reset: 'render' | 'effect') {
    let show: (id: string) => void = () => undefined;
    function Host() {
        const [id, setId] = useState<string | null>(null);
        show = setId;
        return id ? <Picker id={id} reset={reset} /> : null;
    }
    render(<Host />);
    return { show: (id: string) => show(id) };
}

const picked = () => screen.getByTestId('picked').textContent;

it('keeps a click made as the page is drawn', async () => {
    const page = host('render');
    const click = clickAsDrawn(() => screen.queryByRole('button', { name: 'Pick a' }));
    page.show('a');
    await waitFor(() => expect(click.clicked()).toBe(true));
    await waitFor(() => expect(picked()).toBe('a'));
});

it('a reset in an effect loses that click, which is what useChanged is for', async () => {
    const page = host('effect');
    const click = clickAsDrawn(() => screen.queryByRole('button', { name: 'Pick a' }));
    page.show('a');
    await waitFor(() => expect(click.clicked()).toBe(true));
    // The effect that ran after the click put it down again.
    await waitFor(() => expect(screen.getByRole('button', { name: 'Pick a' })).toBeTruthy());
    expect(picked()).toBe('none');
});

it('starts over for another id, and keeps a click made as that one is drawn', async () => {
    const page = host('render');
    act(() => page.show('a'));
    act(() => screen.getByRole('button', { name: 'Pick a' }).click());
    expect(picked()).toBe('a');

    const click = clickAsDrawn(() => screen.queryByRole('button', { name: 'Pick b' }));
    page.show('b');
    await waitFor(() => expect(click.clicked()).toBe(true));
    await waitFor(() => expect(picked()).toBe('b'));

    act(() => page.show('c'));
    expect(picked()).toBe('none');
});

it('is false in the first render and while the keys stay the same', () => {
    const seen: boolean[] = [];
    function Probe({ a, b }: { a: string; b: number }) {
        seen.push(useChanged(a, b));
        return null;
    }
    const view = render(<Probe a="x" b={1} />);
    view.rerender(<Probe a="x" b={1} />);
    view.rerender(<Probe a="x" b={2} />);
    view.rerender(<Probe a="x" b={2} />);
    // The render where b changed answers true once, and React draws it again at once, answering false.
    expect(seen).toEqual([false, false, true, false, false]);
});
