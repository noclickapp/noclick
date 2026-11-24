// @vitest-environment happy-dom
// The slider that rests only on its stops. Stops spread between the thumb's two ends, or sit at their share of the
// track. A drag previews each stop it crosses and commits once, on release; keys step to the neighbouring stop (from a
// value between stops too) and nowhere past either end, committing a moment after the last press; a locked one
// refuses both.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { evenStops, RollText, StopSlider, type SliderStop } from './StopSlider';

afterEach(cleanup);

const LEVELS = ['low', 'medium', 'high', 'max'];
// A 332px track: with a 16px thumb radius, four even stops sit at 16, 116, 216 and 316px.
const WIDTH = 332;
const mouse = { pointerId: 1, pointerType: 'mouse', button: 0 };

function show<T>(stops: readonly SliderStop<T>[], start: T, { at, asShare = false, locked = false }: { at?: (value: T) => number; asShare?: boolean; locked?: boolean } = {}) {
    const previews: T[] = [];
    const commits: T[] = [];
    const refused = vi.fn();
    function Held() {
        const [value, setValue] = useState(start);
        const [preview, setPreview] = useState<T | null>(null);
        const shown = preview ?? value;
        return (
            <StopSlider
                stops={stops}
                value={shown}
                at={at?.(shown)}
                asShare={asShare}
                locked={locked}
                onRefused={refused}
                onPreview={(v) => {
                    previews.push(v);
                    setPreview(v);
                }}
                onCommit={(v) => {
                    commits.push(v);
                    setPreview(null);
                    setValue(v);
                }}
                label="Effort"
                valueText={String(shown)}
                testId="track"
            />
        );
    }
    render(<Held />);
    const track = screen.getByTestId('track');
    Object.defineProperty(track, 'getBoundingClientRect', { value: () => ({ left: 0, top: 0, right: WIDTH, bottom: 44, width: WIDTH, height: 44, x: 0, y: 0, toJSON: () => ({}) }) });
    return { track, slider: screen.getByRole('slider'), previews, commits, refused };
}

it('spreads even stops between the thumb’s two ends, and reads as its stop’s place', () => {
    expect(evenStops(LEVELS).map((s) => s.at)).toEqual([0, 1 / 3, 2 / 3, 1]);
    expect(evenStops(['only'])).toEqual([{ value: 'only', at: 0 }]);
    const { slider } = show(evenStops(LEVELS), 'high');
    expect([slider.getAttribute('aria-valuemin'), slider.getAttribute('aria-valuemax'), slider.getAttribute('aria-valuenow'), slider.getAttribute('aria-valuetext')]).toEqual(['0', '3', '2', 'high']);
});

it('previews each stop a drag crosses and commits once, where it was let go', () => {
    const { track, slider, previews, commits } = show(evenStops(LEVELS), 'high');
    fireEvent.pointerDown(slider, { ...mouse, clientX: 216 });
    fireEvent.pointerMove(track, { ...mouse, clientX: 130 });
    fireEvent.pointerMove(track, { ...mouse, clientX: 20 });
    // Between stops it snaps to the nearest; past the end it stays on the last.
    fireEvent.pointerMove(track, { ...mouse, clientX: 100 });
    fireEvent.pointerMove(track, { ...mouse, clientX: 500 });
    expect(previews).toEqual(['medium', 'low', 'medium', 'max']);
    expect(commits).toEqual([]);
    fireEvent.pointerUp(track, { ...mouse, clientX: 500 });
    expect(commits).toEqual(['max']);
    expect(slider.getAttribute('aria-valuetext')).toBe('max');
});

it('a press on the track goes to the nearest stop', () => {
    const { track, commits } = show(evenStops(LEVELS), 'high');
    fireEvent.pointerDown(track, { ...mouse, clientX: 30 });
    fireEvent.pointerUp(track, { ...mouse, clientX: 30 });
    expect(commits).toEqual(['low']);
});

it('keys step to the neighbouring stop and nowhere past either end, committing a moment after the last press', async () => {
    const { slider, previews, commits } = show(evenStops(LEVELS), 'high');
    fireEvent.keyDown(slider, { key: 'ArrowRight' });
    fireEvent.keyDown(slider, { key: 'ArrowRight' });
    fireEvent.keyDown(slider, { key: 'Home' });
    fireEvent.keyDown(slider, { key: 'ArrowLeft' });
    fireEvent.keyDown(slider, { key: 'ArrowUp' });
    expect(previews).toEqual(['max', 'low', 'medium']);
    expect(commits).toEqual([]);
    await act(() => new Promise((r) => setTimeout(r, 520)));
    expect(commits).toEqual(['medium']);
});

it('steps from a value between stops to its neighbour, the stops sitting at their share of the track', async () => {
    const shares: SliderStop<number>[] = [0.25, 0.5, 0.75, 1].map((value) => ({ value, at: value }));
    const up = show(shares, 0.6, { at: (v) => v, asShare: true });
    fireEvent.keyDown(up.slider, { key: 'ArrowRight' });
    expect(up.previews).toEqual([0.75]);
    cleanup();
    const down = show(shares, 0.6, { at: (v) => v, asShare: true });
    fireEvent.keyDown(down.slider, { key: 'ArrowLeft' });
    expect(down.previews).toEqual([0.5]);
    // A press at a share of the track lands on that share's stop.
    fireEvent.pointerDown(down.track, { ...mouse, clientX: WIDTH * 0.26 });
    fireEvent.pointerUp(down.track, { ...mouse, clientX: WIDTH * 0.26 });
    expect(down.commits).toEqual([0.25]);
});

it('refuses a press and a key while locked', async () => {
    const { track, slider, previews, commits, refused } = show(evenStops(LEVELS), 'high', { locked: true });
    expect(slider.getAttribute('aria-disabled')).toBe('true');
    fireEvent.pointerDown(track, { ...mouse, clientX: 30 });
    fireEvent.pointerUp(track, { ...mouse, clientX: 30 });
    fireEvent.keyDown(slider, { key: 'End' });
    await act(() => new Promise((r) => setTimeout(r, 520)));
    expect(refused).toHaveBeenCalledTimes(2);
    expect([previews, commits]).toEqual([[], []]);
});

it('rolls a stop’s name to the next one', () => {
    const view = render(<RollText text="High" order={2} testId="name" />);
    expect(screen.getByTestId('name').textContent).toBe('High');
    view.rerender(<RollText text="Max" order={3} testId="name" />);
    expect(screen.getByTestId('name').textContent).toBe('Max');
});
