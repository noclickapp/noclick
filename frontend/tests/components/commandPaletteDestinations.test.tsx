// @vitest-environment jsdom
// The command palette goes everywhere the app does, from the tables the pages themselves read: every shell page,
// every Resources kind the instance has and its page for getting one, every Settings section the account sees, and
// Connections' tabs. What people type instead of a page's name finds it, and a page named exactly beats the page that
// holds it.
import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const env = vi.hoisted(() => ({ billing: true, phoneLinking: true, org: null as string | null, personalOrg: 'p1' as string | null }));
vi.mock('~/hooks/useInstanceCapabilities', () => ({ useInstanceCapabilities: () => ({ billing: env.billing }) }));
vi.mock('~/hooks/usePhoneLinking', () => ({ usePhoneLinkingAvailable: () => env.phoneLinking }));
vi.mock('~/hooks/useOrgContext', () => ({ useOrgContext: () => [{ id: env.org, role: 'owner', isPersonalWorkspace: !env.org }, vi.fn()] }));
vi.mock('~/hooks/useValtioState', () => ({ useValtioState: () => [env.personalOrg, vi.fn()] }));

import { appDestinations, type DestinationContext } from '~/components/command/destinations';
import { layoutCommands, type Cmd } from '~/components/command/layout';
import type { PaletteEntry } from '~/components/command/sources';
import { SETTINGS_SECTION_DEFS, useSettingsSections, type VisibleSettingsSection } from '~/components/settings/sections';
import { CONNECTIONS_VIEWS } from '~/components/shell/connections/views';
import { SHELL_PAGES } from '~/components/shell/pages';
import { KINDS, visibleKinds } from '~/components/shell/resources/kinds';
import { consumePendingFlowIntent } from '~/lib/navigation';

function sections(hidden: Parameters<typeof useSettingsSections>[0] = []): VisibleSettingsSection[] {
    return renderHook(() => useSettingsSections(hidden)).result.current;
}

function shell(over: Partial<DestinationContext> = {}): DestinationContext {
    return { shell: true, kinds: visibleKinds({ platform: true }), billing: true, inOrganization: true, settings: sections(), ...over };
}

const ids = (entries: PaletteEntry[]) => entries.map((e) => e.id);
const byLabel = (entries: PaletteEntry[], label: string) => entries.find((e) => e.label === label)!;

/** What the palette shows first for `query`, as "Name (Context)". */
function ranked(query: string, ctx = shell()): string[] {
    const commands: Cmd[] = appDestinations(ctx).map((e) => ({ ...e, section: 'Go to' }));
    return layoutCommands(commands, query, null, {})
        .flatMap((s) => s.items)
        .map((c) => (c.context ? `${c.label} (${c.context})` : c.label));
}

let switches: { tab: string; section?: string; params?: Record<string, string | null> }[] = [];
const onSwitch = (e: Event) => switches.push((e as CustomEvent).detail);

beforeEach(() => {
    Object.assign(env, { billing: true, phoneLinking: true, org: null, personalOrg: 'p1' });
    switches = [];
    window.addEventListener('noclick:switch-tab', onSwitch);
});
afterEach(() => window.removeEventListener('noclick:switch-tab', onSwitch));

describe('every place the app has', () => {
    it('lists each shell page, before anything is typed', () => {
        const pages = appDestinations(shell()).filter((e) => e.browse);
        expect(pages.map((e) => e.label)).toEqual(SHELL_PAGES.map((p) => p.label));
    });

    it('lists each resource kind the instance has, and the page for getting one where one can be got by hand', () => {
        const all = appDestinations(shell());
        for (const kind of KINDS) expect(ids(all)).toContain(`nav:resources:${kind.id}`);
        expect(all.filter((e) => e.id.endsWith(':new')).map((e) => e.label)).toEqual(['Buy a number', 'Buy a domain', 'New address']);

        // Nothing bought without billing; an address is made, not bought.
        const unbilled = appDestinations(shell({ billing: false }));
        expect(unbilled.filter((e) => e.id.endsWith(':new')).map((e) => e.label)).toEqual(['New address']);

        // Without the platform, only its kinds go.
        const local = appDestinations(shell({ kinds: visibleKinds({ platform: false }) }));
        expect(local.filter((e) => e.context === 'Resources' && !e.id.endsWith(':new')).map((e) => e.label)).toEqual(
            KINDS.filter((k) => !k.platform).map((k) => k.label)
        );
    });

    it('lists each Settings section the account sees, and none its host shows as a page of its own', () => {
        const seen = sections();
        // Everything but the self-hosted keys, on a hosted instance with billing and phone linking.
        expect(seen.map((s) => s.id)).toEqual(SETTINGS_SECTION_DEFS.map((s) => s.id).filter((id) => id !== 'oauth-apps'));
        expect(ids(appDestinations(shell({ settings: seen })))).toEqual(expect.arrayContaining(seen.map((s) => `nav:settings:${s.id}`)));

        expect(sections(['credentials']).map((s) => s.id)).not.toContain('credentials');
        env.billing = false;
        env.phoneLinking = false;
        env.personalOrg = null;
        expect(sections().map((s) => s.id)).toEqual(['usage', 'credentials', 'skills', 'notifications', 'popups', 'developer']);
    });

    it("lists Connections' tabs, Workspace only in an organization", () => {
        const tabs = (inOrganization: boolean) => appDestinations(shell({ inOrganization })).filter((e) => e.context === 'Connections').map((e) => e.label);
        expect(tabs(true)).toEqual(CONNECTIONS_VIEWS.map((v) => v.label));
        expect(tabs(false)).toEqual(['All apps', 'Connected', 'Shared with me']);
    });

    it("runs the open edition's tabbed layout: its pages, Trash and Settings, and nothing of the shell's", () => {
        const open = appDestinations(shell({ shell: false }));
        expect(open.filter((e) => e.browse).map((e) => e.label)).toEqual(['Workflows', 'Dashboard', 'Needs you', 'Settings']);
        expect(open.some((e) => e.context === 'Resources' || e.context === 'Connections')).toBe(false);
        expect(byLabel(open, 'Trash').context).toBe('Workflows');
    });

    it('opens each at its own address, leaving whatever was open inside the page before', () => {
        const all = appDestinations(shell());
        byLabel(all, 'Domains').run();
        byLabel(all, 'Buy a domain').run();
        byLabel(all, 'Resources').run();
        byLabel(all, 'Connected').run();
        byLabel(all, 'Members').run();
        expect(switches).toEqual([
            { tab: 'resources', params: expect.objectContaining({ kind: 'domains', new: null, resource: null, path: null }) },
            { tab: 'resources', params: expect.objectContaining({ kind: 'domains', new: '1', resource: null }) },
            { tab: 'resources', params: expect.objectContaining({ kind: null, new: null }) },
            { tab: 'connections', params: { view: 'connected', account: null } },
            { tab: 'settings', section: 'organization', orgTab: undefined },
        ]);

        byLabel(all, 'Trash').run();
        expect(consumePendingFlowIntent()).toEqual({ kind: 'action', action: 'trash' });
    });
});

describe('what people type', () => {
    it('finds a place by its own name ahead of the page that holds it', () => {
        expect(ranked('domains').slice(0, 2)).toEqual(['Domains (Resources)', 'Buy a domain (Resources)']);
        expect(ranked('resources')[0]).toBe('Resources');
        expect(ranked('go to usage')[0]).toBe('Usage (Settings)');
        expect(ranked('resources domains')[0]).toBe('Domains (Resources)');
        expect(ranked('buy domain')[0]).toBe('Buy a domain (Resources)');
    });

    it('finds a place by the other words people use for it', () => {
        expect(ranked('dns')[0]).toBe('Domains (Resources)');
        expect(ranked('site')[0]).toBe('Websites (Resources)');
        expect(ranked('website')[0]).toBe('Websites (Resources)');
        expect(ranked('repo')[0]).toBe('Code (Resources)');
        expect(ranked('git')[0]).toBe('Code (Resources)');
        expect(ranked('invite')[0]).toBe('Members (Settings)');
        expect(ranked('deleted')[0]).toBe('Trash (Automations)');
        // Settings → Phone is named exactly; your numbers come straight after it, ahead of everything that holds them.
        expect(ranked('phone').slice(0, 2)).toEqual(['Phone (Settings)', 'Numbers (Resources)']);
        env.phoneLinking = false;
        expect(ranked('phone', shell({ settings: sections() }))[0]).toBe('Numbers (Resources)');
    });

    // The open edition has no plans: its export strips the section.
    it.runIf(SETTINGS_SECTION_DEFS.some((s) => s.label === 'Plan and billing'))('finds the plan by the words for money', () => {
        for (const q of ['billing', 'plan', 'balance', 'subscription']) expect(ranked(q)[0]).toBe('Plan and billing (Settings)');
    });

    it('offers the places run most lately first, before anything is typed, and lets them break ties', () => {
        const commands: Cmd[] = appDestinations(shell()).map((e) => ({ ...e, section: 'Go to' }));
        const now = Date.now();
        const uses = { 'nav:resources:repos': { count: 1, at: now - 1000 }, 'nav:settings:skills': { count: 9, at: now - 5000 } };
        const browse = layoutCommands(commands, '', null, uses, now);
        expect(browse[0]).toMatchObject({ title: 'Recent', items: [{ label: 'Code' }, { label: 'Skills' }] });
        expect(browse[1].items.map((c) => c.label)).toEqual(SHELL_PAGES.map((p) => p.label));

        // "s" starts Settings, Skills, Storage and Shared with me alike: the one used most leads.
        const s = layoutCommands(commands, 's', null, uses, now)[0].items.map((c) => c.label);
        expect(s[0]).toBe('Skills');
    });
});
