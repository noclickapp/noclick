// @vitest-environment happy-dom
// What Work remembers each view had open, per space, on this device: kept apart by space and by view, read from an
// older value that held Home's channel alone, written only when it changes, and silent where storage is blocked.
// `spotOf` says what a place has open that its view can reopen.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readPlace } from './place';
import { lastChannel, lastSpot, rememberSpot, spotOf } from './remember';

const VIEWS_KEY = 'nc-work-channels';
const place = (query: string) => readPlace(new URLSearchParams(query));

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe('remembering what each view had open', () => {
    it('keeps each view of each space apart', () => {
        rememberSpot('home', 'agents', { agent: 'agt_growth' });
        rememberSpot('home', 'dms', { channel: 'dm_priya' });
        rememberSpot('ws_acme', 'agents', { agent: 'agt_ops', profile: true });
        rememberSpot('home', 'home', { channel: 'ch_launch', thread: 'l4' });

        expect(lastSpot('home', 'agents')).toEqual({ agent: 'agt_growth' });
        expect(lastSpot('home', 'dms')).toEqual({ channel: 'dm_priya' });
        expect(lastSpot('ws_acme', 'agents')).toEqual({ agent: 'agt_ops', profile: true });
        expect(lastSpot('ws_acme', 'dms')).toBeNull();
        expect(lastSpot('home', 'resources')).toBeNull();
        expect(lastChannel('home')).toBe('ch_launch');
        expect(lastChannel('ws_acme')).toBeNull();
    });

    it('replaces a view’s spot whole, so a thread or profile closed since isn’t reopened', () => {
        rememberSpot('home', 'home', { channel: 'ch_launch', thread: 'l4' });
        rememberSpot('home', 'home', { channel: 'ch_launch' });
        expect(lastSpot('home', 'home')).toEqual({ channel: 'ch_launch' });
        rememberSpot('home', 'agents', { agent: 'agt_growth', profile: true });
        rememberSpot('home', 'agents', { agent: 'agt_growth' });
        expect(lastSpot('home', 'agents')).toEqual({ agent: 'agt_growth' });
    });

    it('keeps Resources’ overview, which names nothing', () => {
        rememberSpot('home', 'resources', { res: 'skills', item: 'skills:sk_1' });
        rememberSpot('home', 'resources', {});
        expect(lastSpot('home', 'resources')).toEqual({});
    });

    it('reads an older value, Home’s channel alone, as Home’s, and keeps it beside the other views', () => {
        localStorage.setItem(VIEWS_KEY, JSON.stringify({ home: 'ch_launch', ws_acme: 'ch_acme' }));
        expect(lastChannel('home')).toBe('ch_launch');
        expect(lastSpot('home', 'home')).toEqual({ channel: 'ch_launch' });

        rememberSpot('home', 'agents', { agent: 'agt_growth' });
        expect(lastChannel('home')).toBe('ch_launch');
        expect(lastSpot('home', 'agents')).toEqual({ agent: 'agt_growth' });
        expect(lastChannel('ws_acme')).toBe('ch_acme');
    });

    it('writes only when what’s open changed', () => {
        rememberSpot('home', 'agents', { agent: 'agt_growth' });
        const set = vi.spyOn(window.localStorage, 'setItem');
        rememberSpot('home', 'agents', { agent: 'agt_growth' });
        expect(set).not.toHaveBeenCalled();
        rememberSpot('home', 'agents', { agent: 'agt_ops' });
        expect(set).toHaveBeenCalledTimes(1);
    });

    it('opens on nothing remembered where storage is blocked or holds something unreadable', () => {
        localStorage.setItem(VIEWS_KEY, '{not json');
        expect(lastSpot('home', 'agents')).toBeNull();
        vi.spyOn(window.localStorage, 'getItem').mockImplementation(() => {
            throw new Error('blocked');
        });
        vi.spyOn(window.localStorage, 'setItem').mockImplementation(() => {
            throw new Error('blocked');
        });
        expect(() => rememberSpot('home', 'dms', { channel: 'dm_priya' })).not.toThrow();
        expect(lastSpot('home', 'dms')).toBeNull();
        expect(lastChannel('home')).toBeNull();
    });
});

describe('what a place has open that its view can reopen', () => {
    const channel = { id: 'ch_launch', kind: 'channel' };
    const dm = { id: 'dm_priya', kind: 'dm' };

    it('Home: the channel the page opened and its thread, or its threads', () => {
        expect(spotOf(place('channel=ch_launch&thread=l4'), channel)).toEqual({ channel: 'ch_launch', thread: 'l4' });
        expect(spotOf(place(''), channel)).toEqual({ channel: 'ch_launch' });
        expect(spotOf(place('channel=threads'), null)).toEqual({ channel: 'threads' });
        // A DM named in Home moves to DMs; a channel not found yet is nothing.
        expect(spotOf(place('channel=dm_priya'), dm)).toBeNull();
        expect(spotOf(place('channel=ch_gone'), null)).toBeNull();
    });

    it('DMs: the DM the page opened, never a channel', () => {
        expect(spotOf(place('show=dms&channel=dm_priya'), dm)).toEqual({ channel: 'dm_priya' });
        expect(spotOf(place('show=dms'), null)).toBeNull();
        expect(spotOf(place('show=dms&channel=ch_launch'), channel)).toBeNull();
    });

    it('Agents: the agent and whether its profile is beside (its one session needs no name), never a new agent’s draft', () => {
        expect(spotOf(place('show=agents&agent=agt_growth'), null)).toEqual({ agent: 'agt_growth' });
        expect(spotOf(place('show=agents&agent=agt_growth&conversation=main&panel=profile'), null)).toEqual({ agent: 'agt_growth', profile: true });
        expect(spotOf(place('show=agents&agent=agt_growth&panel=people'), null)).toEqual({ agent: 'agt_growth' });
        expect(spotOf(place('show=agents&agent=new'), null)).toBeNull();
        expect(spotOf(place('show=agents'), null)).toBeNull();
    });

    it('Resources: its kind and item, or its overview', () => {
        expect(spotOf(place('show=resources&res=skills&item=skills:sk_1'), null)).toEqual({ res: 'skills', item: 'skills:sk_1' });
        expect(spotOf(place('show=resources&res=machines'), null)).toEqual({ res: 'machines' });
        expect(spotOf(place('show=resources'), null)).toEqual({});
    });
});
