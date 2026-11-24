// @vitest-environment happy-dom
// What NoClick uses of a computer of yours, picked on one slider whose track is the split: three quarters until you
// say, snapping to the four parts under a pointer, a finger or keys, saved once when let go (after keys, a moment
// after the last press) and what it comes to in CPUs and memory once the computer reported its size, a refusal in the
// API's words with the slider back where it was, and a Mac whose VM is made, which keeps its size.
import {
    act,
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor,
} from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import {
    toOwnComputer,
    type OwnComputer,
} from '@/screens/resources/knowledge';
import { fakeWork } from '../agents/fixtures/workAgents';
import { WorkClientContext } from '../client';
import { ShareChoice } from './ShareChoice';
import { splitOf } from './share';

afterEach(cleanup);

const ONLINE = {
    object: 'machine',
    id: 'm-own-1',
    kind: 'own',
    name: 'rowan-mini',
    status: 'running',
    os: 'Ubuntu 24.04.1 LTS',
    cpu: 8,
    memory_gb: 32,
    conversations_at_once: 6,
    agent_share: 0.75,
    agent_share_fixed: false,
    pairing: null,
};

// A 400px track: the stops sit at 100, 200 and 300px, and All of it a thumb's radius in from the end, at 384px.
const WIDTH = 400;
const AT = { quarter: 100, half: 200, threeQuarters: 300, all: 384 };

function show(computer: OwnComputer, fake = fakeWork(), mac = false) {
    render(
        <WorkClientContext.Provider value={fake.client}>
            <ShareChoice computer={computer} mac={mac} />
        </WorkClientContext.Provider>
    );
    const track = screen.getByTestId('share-track');
    Object.defineProperty(track, 'getBoundingClientRect', {
        value: () => ({
            left: 0,
            top: 0,
            right: WIDTH,
            bottom: 44,
            width: WIDTH,
            height: 44,
            x: 0,
            y: 0,
            toJSON: () => ({}),
        }),
    });
    return { fake, track, slider: screen.getByRole('slider') };
}

const patches = (fake: ReturnType<typeof fakeWork>) =>
    fake.requests.filter((r) => r.method === 'PATCH');
const said = () => [
    screen.getByRole('slider').getAttribute('aria-valuetext'),
    screen.getByTestId('share-stop').textContent,
];
const split = () => [
    screen.getByTestId('share-noclick').textContent,
    screen.getByTestId('share-you').textContent,
];
const mouse = { pointerId: 1, pointerType: 'mouse', button: 0 };
const finger = { pointerId: 2, pointerType: 'touch' };

it('stops at four parts, three quarters until you say, and says which to pick before the computer reported', () => {
    const { slider } = show(
        toOwnComputer({
            ...ONLINE,
            status: 'provisioning',
            cpu: null,
            memory_gb: null,
            conversations_at_once: null,
        })
    );
    expect([
        slider.getAttribute('aria-valuemin'),
        slider.getAttribute('aria-valuenow'),
        slider.getAttribute('aria-valuemax'),
    ]).toEqual(['0.25', '0.75', '1']);
    expect(said()).toEqual(['Three quarters', 'Three quarters']);
    expect(screen.queryByTestId('share-noclick')).toBeNull();
    expect(screen.getByTestId('share-note').textContent).toBe(
        'A server just for NoClick: all of it. A computer you use: half or less, so it stays quick for you.'
    );
    expect(slider.getAttribute('aria-describedby')).toBe(
        screen.getByTestId('share-note').id
    );
    cleanup();
    show(
        toOwnComputer({
            ...ONLINE,
            status: 'provisioning',
            cpu: null,
            memory_gb: null,
        }),
        fakeWork(),
        true
    );
    expect(screen.getByTestId('share-note').textContent).toBe(
        'On a Mac, NoClick’s VM is made this size when you run the command, and keeps it.'
    );
});

it('a drag shows each part it crosses and saves once, on release, what each then gets', async () => {
    const fake = fakeWork();
    fake.machines.push({ ...ONLINE });
    const { track, slider } = show(toOwnComputer(ONLINE), fake);
    expect(split()).toEqual(['6 CPUs · 24 GB', 'You keep 2 CPUs · 8 GB']);
    expect(
        screen.getByText(/Up to 6 agents at once/).textContent
    ).toContain('What you keep stays yours');

    fireEvent.pointerDown(slider, { ...mouse, clientX: AT.threeQuarters });
    fireEvent.pointerMove(track, { ...mouse, clientX: 240 });
    expect(said()[0]).toBe('Half, 4 CPUs and 16 GB');
    fireEvent.pointerMove(track, { ...mouse, clientX: 90 });
    expect(said()[0]).toBe('A quarter, 2 CPUs and 8 GB');
    // Between stops it snaps to the nearest.
    fireEvent.pointerMove(track, { ...mouse, clientX: 185 });
    expect(said()).toEqual(['Half, 4 CPUs and 16 GB', 'Half']);
    expect(patches(fake)).toEqual([]);

    fireEvent.pointerUp(track, { ...mouse, clientX: 185 });
    await waitFor(() => expect(patches(fake)).toHaveLength(1));
    expect(patches(fake)[0]).toMatchObject({
        path: '/v1/machines/m-own-1',
        body: { agent_share: 0.5 },
    });
    expect(slider.getAttribute('aria-valuenow')).toBe('0.5');
    await waitFor(() =>
        expect(split()).toEqual(['4 CPUs · 16 GB', 'You keep 4 CPUs · 16 GB'])
    );
    await waitFor(() =>
        expect(screen.getByTestId('share-note').textContent).toContain(
            'each takes its new size when it next starts'
        )
    );
    await waitFor(() =>
        expect(screen.getByTestId('share-saving').textContent).toBe('Saved')
    );
    // Let go where it was: nothing more to save.
    fireEvent.pointerDown(slider, { ...mouse, clientX: AT.half });
    fireEvent.pointerUp(track, { ...mouse, clientX: AT.half });
    await act(() => new Promise((r) => setTimeout(r, 50)));
    expect(patches(fake)).toHaveLength(1);
});

it('a tap snaps to the nearest stop; a finger waits to lift, and a scroll that starts on the track changes nothing', async () => {
    const fake = fakeWork();
    fake.machines.push({ ...ONLINE });
    const { track, slider } = show(toOwnComputer(ONLINE), fake);

    fireEvent.pointerDown(track, { ...mouse, clientX: 360 });
    expect(slider.getAttribute('aria-valuenow')).toBe('1');
    expect(patches(fake)).toEqual([]);
    fireEvent.pointerUp(track, { ...mouse, clientX: 360 });
    await waitFor(() =>
        expect(patches(fake).map((r) => r.body)).toEqual([{ agent_share: 1 }])
    );
    await waitFor(() =>
        expect(split()).toEqual(['8 CPUs · 32 GB', 'You keep nothing'])
    );

    fireEvent.pointerDown(track, { ...finger, clientX: 110 });
    expect(slider.getAttribute('aria-valuenow')).toBe('1');
    fireEvent.pointerCancel(track, { ...finger, clientX: 110 });
    await act(() => new Promise((r) => setTimeout(r, 50)));
    expect(slider.getAttribute('aria-valuenow')).toBe('1');
    expect(patches(fake)).toHaveLength(1);

    fireEvent.pointerDown(track, { ...finger, clientX: 110 });
    fireEvent.pointerUp(track, { ...finger, clientX: 110 });
    expect(slider.getAttribute('aria-valuenow')).toBe('0.25');
    await waitFor(() => expect(patches(fake)).toHaveLength(2));
    expect(patches(fake)[1].body).toEqual({ agent_share: 0.25 });
});

it('keys step through the stops, Home and End go to either end, and it saves a moment after the last press', async () => {
    const fake = fakeWork();
    fake.machines.push({ ...ONLINE });
    const { slider } = show(toOwnComputer(ONLINE), fake);
    slider.focus();
    fireEvent.keyDown(slider, { key: 'ArrowLeft' });
    expect(said()[1]).toBe('Half');
    fireEvent.keyDown(slider, { key: 'ArrowDown' });
    expect(said()[1]).toBe('A quarter');
    fireEvent.keyDown(slider, { key: 'ArrowLeft' });
    expect(said()[1]).toBe('A quarter');
    fireEvent.keyDown(slider, { key: 'End' });
    expect(said()[1]).toBe('All of it');
    fireEvent.keyDown(slider, { key: 'Home' });
    expect(said()[1]).toBe('A quarter');
    fireEvent.keyDown(slider, { key: 'PageUp' });
    fireEvent.keyDown(slider, { key: 'ArrowUp' });
    fireEvent.keyDown(slider, { key: 'ArrowRight' });
    expect(said()).toEqual(['All of it, 8 CPUs and 32 GB', 'All of it']);
    expect(patches(fake)).toEqual([]);
    await waitFor(() =>
        expect(patches(fake).map((r) => r.body)).toEqual([{ agent_share: 1 }])
    );
    fireEvent.keyDown(slider, { key: 'ArrowRight' });
    fireEvent.keyDown(slider, { key: 'Tab' });
    await act(() => new Promise((r) => setTimeout(r, 600)));
    expect(patches(fake)).toHaveLength(1);
});

it('a refusal says why in the API’s words and the slider goes back to the part it had', async () => {
    const fake = fakeWork();
    fake.machines.push({ ...ONLINE });
    const refusal =
        'A quarter of rowan-mini’s 8 CPUs and 32 GB leaves its agents too little.';
    fake.failNext('PATCH', '/v1/machines/m-own-1', 400, refusal);
    const { track, slider } = show(toOwnComputer(ONLINE), fake);
    fireEvent.pointerDown(track, { ...mouse, clientX: AT.quarter });
    fireEvent.pointerUp(track, { ...mouse, clientX: AT.quarter });
    expect(slider.getAttribute('aria-valuenow')).toBe('0.25');
    await waitFor(() =>
        expect(screen.getByRole('alert').textContent).toContain(refusal)
    );
    expect(said()).toEqual([
        'Three quarters, 6 CPUs and 24 GB',
        'Three quarters',
    ]);
    expect(screen.getByTestId('share-saving').textContent).toBe('');
    // Picking again clears it.
    fireEvent.pointerDown(track, { ...mouse, clientX: AT.half });
    fireEvent.pointerUp(track, { ...mouse, clientX: AT.half });
    expect(screen.queryByRole('alert')).toBeNull();
    await waitFor(() =>
        expect(patches(fake).map((r) => r.body)).toEqual([
            { agent_share: 0.25 },
            { agent_share: 0.5 },
        ])
    );
});

it('a Mac whose VM is made keeps its size: locked to pointer and keys, and the rest of the Mac is yours', async () => {
    const fake = fakeWork();
    const { track, slider } = show(
        toOwnComputer({
            ...ONLINE,
            os: 'Ubuntu 24.04.3 LTS (VM on macOS 15.1)',
            cpu: 6,
            memory_gb: 12,
            agent_share: 0.5,
            agent_share_fixed: true,
        }),
        fake
    );
    expect(slider.getAttribute('aria-disabled')).toBe('true');
    expect(screen.getByTestId('share-locked')).toBeTruthy();
    expect(said()).toEqual(['Half, 6 CPUs and 12 GB', 'Half']);
    expect(split()).toEqual(['6 CPUs · 12 GB', 'You keep the rest of the Mac']);
    const note = screen.getByTestId('share-note');
    expect(note.textContent).toContain(
        'remove NoClick from the Mac and add it again'
    );
    expect(note.dataset.flash).toBeUndefined();

    fireEvent.pointerDown(track, { ...mouse, clientX: AT.all });
    fireEvent.pointerUp(track, { ...mouse, clientX: AT.all });
    expect(note.dataset.flash).toBe('true');
    fireEvent.keyDown(slider, { key: 'End' });
    fireEvent.keyDown(slider, { key: 'ArrowRight' });
    await act(() => new Promise((r) => setTimeout(r, 600)));
    expect(slider.getAttribute('aria-valuenow')).toBe('0.5');
    expect(patches(fake)).toEqual([]);
    await waitFor(() => expect(note.dataset.flash).toBeUndefined());
});

it('splits a computer between NoClick and you, counting in whole numbers on the way', () => {
    expect(splitOf(8, 32, 1, false)).toEqual({
        noclick: '8 CPUs · 32 GB',
        you: 'nothing',
    });
    expect(splitOf(6, 16, 0.25, false)).toEqual({
        noclick: '1.5 CPUs · 4 GB',
        you: '4.5 CPUs · 12 GB',
    });
    expect(splitOf(4, 8, 0.25, false).noclick).toBe('1 CPU · 2 GB');
    expect(splitOf(6, 12, 0.5, true)).toEqual({
        noclick: '6 CPUs · 12 GB',
        you: 'the rest of the Mac',
    });
    expect(splitOf(6, 16, 0.31, false, true)).toEqual({
        noclick: '2 CPUs · 5 GB',
        you: '4 CPUs · 11 GB',
    });
    expect(splitOf(8, 32, 0.99, false, true).you).toBe('nothing');
});
