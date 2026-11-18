// The console's sections: six fixed sidebar items (the same for every account,
// so nothing moves as an account grows), Settings at the foot, and the pages
// reached only from inside them (an agent, the Quickstart). Earlier addresses
// map onto today's. Pages are found by glob, so a page that hasn't been written
// yet renders a "Not built yet" stub instead of breaking the build.
import { lazy, type ComponentType, type LazyExoticComponent } from 'react';
import { ChartColumn, House, KeyRound, Layers, Rocket, ScrollText, Settings, SquareTerminal, Users, type LucideIcon } from 'lucide-react';
import type { OwnerOnly } from './ownerOnly';
import { visibleKinds } from './resourceKinds';

export type SectionId = 'home' | 'users' | 'resources' | 'logs' | 'usage' | 'keys' | 'settings' | 'agents' | 'quickstart' | 'cli';

export interface SectionDef {
    id: SectionId;
    label: string;
    /** The sentence under the page title. */
    purpose: string;
    icon: LucideIcon;
    /** Other words people use for it, which the app's command palette matches. */
    keywords?: string;
    /** Sits at the foot of the sidebar instead of in the main list. */
    footer?: boolean;
    /** Reached from inside another page, never listed in the sidebar. */
    hidden?: boolean;
    /** The whole section is something only the account's signed-in owner can do (ownerOnly.ts): a console acting as a
     *  key doesn't list it, and says why at its address. */
    ownerOnly?: OwnerOnly;
    /** The sidebar item lit while this section is open (an agent lives under Home). */
    navId?: SectionId;
    /** The page module for the list, and for `/<section>/<id>` when it has a detail page. */
    page: string;
    detailPage?: string;
}

export const SECTIONS: readonly SectionDef[] = [
    { id: 'home', label: 'Home', purpose: 'Every agent you run, and what it is doing.', icon: House, keywords: 'developer console developers platform agents', page: 'Home' },
    { id: 'users', label: 'Users', purpose: 'The people and companies your product acts for.', icon: Users, keywords: 'tenants customers end users', page: 'Users', detailPage: 'UserDetail' },
    { id: 'resources', label: 'Resources', purpose: 'What your agents and apps use: accounts they act in, numbers and inboxes, machines that run code, and where data lives.', icon: Layers, page: 'Resources' },
    { id: 'logs', label: 'Logs', purpose: 'Everything that ran, what each call did, and why anything failed.', icon: ScrollText, keywords: 'runs operations errors activity', page: 'Logs' },
    { id: 'usage', label: 'Usage', purpose: 'What this month cost, where it went, and the caps that bound it.', icon: ChartColumn, keywords: 'costs spend caps limits', page: 'Usage' },
    { id: 'keys', label: 'API keys', purpose: 'A secret key builds and spends for this account, so keep it on your server. A publishable key only calls what you made public, so it can go in a page.', icon: KeyRound, keywords: 'api key api keys keys secret key publishable key token', ownerOnly: 'keys', page: 'Keys' },
    { id: 'settings', label: 'Settings', purpose: 'Approval rules, your brand, and connecting your coding tools.', icon: Settings, keywords: 'approvals policy brand coding tools', footer: true, page: 'Settings' },
    { id: 'agents', label: 'Agents', purpose: 'A hosted agent.', icon: House, hidden: true, navId: 'home', page: 'Home', detailPage: 'AgentDetail' },
    { id: 'quickstart', label: 'Quickstart', purpose: 'Build your first agent.', icon: Rocket, hidden: true, navId: 'home', page: 'Quickstart' },
    // `noclick login` links here; approving a sign-in creates an API key.
    { id: 'cli', label: 'Sign in the CLI', purpose: 'Approve a sign-in your terminal started: it gets an API key of its own, named after the machine.', icon: SquareTerminal, hidden: true, navId: 'keys', ownerOnly: 'cliSignIn', page: 'CliLogin' },
];

const BY_ID = new Map(SECTIONS.map((s) => [s.id, s]));

export function sectionById(id: SectionId): SectionDef {
    return BY_ID.get(id)!;
}

/**
 * Where a sub-page of Settings or Logs lives, for links and the palette. A
 * `designed` one (drawn, with no API behind it yet) exists only in the lab.
 */
export const SETTINGS_PAGES: readonly { id: string; label: string; page: string; designed?: boolean }[] = [
    { id: 'policy', label: 'Approval rules', page: 'Policy' },
    { id: 'brand', label: 'Brand', page: 'Brand' },
    { id: 'install', label: 'Clients and MCP', page: 'Settings' },
    { id: 'webhooks', label: 'Webhooks', page: 'Webhooks' },
];

export const LOG_VIEWS = [
    { id: 'runs', label: 'Runs' },
    { id: 'tool-calls', label: 'Tool calls' },
    { id: 'requests', label: 'API requests' },
    { id: 'events', label: 'Events' },
] as const;

export type LogView = (typeof LOG_VIEWS)[number]['id'];

/** The Logs views this console shows: designed ones only in the lab. */
export function logViews(lab: boolean): readonly (typeof LOG_VIEWS)[number][] {
    return LOG_VIEWS.filter((v) => lab || !('designed' in v));
}

/** The Settings sub-pages this console shows: designed ones only in the lab. */
export function settingsPages(lab: boolean): readonly (typeof SETTINGS_PAGES)[number][] {
    return SETTINGS_PAGES.filter((p) => lab || !p.designed);
}

/** Whether whoever the console acts as can do one of the things only the owner can (`useOwnerOnly`). */
export type Can = (what: OwnerOnly) => boolean;

const OWNER: Can = () => true;

/** The sections a sidebar lists: the ones not reached from inside another, that whoever the console acts as can open. */
export function listedSections(can: Can = OWNER): readonly SectionDef[] {
    return SECTIONS.filter((s) => !s.hidden && (!s.ownerOnly || can(s.ownerOnly)));
}

/** Everything a palette can jump to: the sections, then the pages inside them and (with `kinds`) each resource kind
 *  (designed ones in the lab). A host's own palette may leave the kinds to its own pages; `can` leaves out what only
 *  the owner opens (without it, everything is listed). */
export function destinations(lab = false, { kinds = true, can = OWNER }: { kinds?: boolean; can?: Can } = {}): { id: string; label: string; path: string; icon: LucideIcon; keywords?: string }[] {
    const listed = listedSections(can).map((s) => ({ id: s.id, label: s.label, path: s.id === 'home' ? '' : s.id, icon: s.icon, keywords: s.keywords }));
    const inner = [
        ...logViews(lab).slice(1).map((v) => ({ id: `logs/${v.id}`, label: v.label, path: `logs/${v.id}`, icon: sectionById('logs').icon })),
        ...settingsPages(lab).map((p) => ({ id: `settings/${p.id}`, label: p.label, path: `settings/${p.id}`, icon: sectionById('settings').icon })),
        ...(kinds ? visibleKinds(lab).map((k) => ({ id: `resources/${k.id}`, label: k.label, path: `resources/${k.id}`, icon: k.icon })) : []),
        { id: 'quickstart', label: 'Quickstart', path: 'quickstart', icon: Rocket },
    ];
    return [...listed, ...inner];
}

/**
 * Earlier layouts' addresses (in-app links, bookmarks and the clients'
 * `consoleUrl`, which prints `/operations?op=`) rewritten to today's. The query
 * string rides along untouched.
 */
export function currentPath(segments: readonly string[]): string[] {
    const [head, ...tail] = segments;
    switch (head) {
        case 'overview':
            return [];
        case 'agents':
            return tail.length ? segments.slice() : [];
        case 'operations':
            return ['logs', ...tail];
        case 'requests':
            // A human request opens read-only on Logs (`/requests?req=` kept working).
            return ['logs'];
        case 'activity':
            if (tail[0] === 'operations') return ['logs', ...tail.slice(1)];
            if (tail[0] === 'logs') return ['logs', 'tool-calls'];
            return ['logs'];
        case 'policy':
        case 'brand':
            return ['settings', head, ...tail];
        case 'tenants':
            return ['users', ...tail];
        case 'settings':
            if (tail[0] === 'keys' || tail[0] === 'usage') return [tail[0]];
            return segments.slice();
        default:
            return segments.slice();
    }
}

export interface SectionRoute {
    /** Null for an unknown path (the shell renders not-found). */
    section: SectionDef | null;
    /** Path segments after the section: `agents/<id>` → `['<id>']`. */
    rest: string[];
}

/** `params['*']` → section; the bare path is Home. */
export function parseSectionPath(splat: string | undefined): SectionRoute {
    // React Router has already decoded the splat; decoding again throws on a literal `%`.
    const segments = currentPath((splat ?? '').split('/').filter(Boolean));
    if (!segments.length) return { section: sectionById('home'), rest: [] };
    return { section: BY_ID.get(segments[0] as SectionId) ?? null, rest: segments.slice(1) };
}

/** Every page gets the path after its section. */
export interface ConsolePageProps {
    rest: string[];
}

type PageModule = { default: ComponentType<ConsolePageProps> };
export type PageLoaders = Record<string, () => Promise<unknown>>;

// Pages only: a test beside them would become a lazy chunk of the build, test runner and all.
const PAGE_LOADERS = import.meta.glob(['./pages/*.tsx', '!./pages/*.test.tsx']) as PageLoaders;

/** The module name a route renders: the detail page when the section has one and an id follows. */
export function pageName(route: SectionRoute): string | null {
    if (!route.section) return null;
    return route.rest.length && route.section.detailPage ? route.section.detailPage : route.section.page;
}

const lazyPages = new Map<string, LazyExoticComponent<ComponentType<ConsolePageProps>>>();

/** The lazy page component for a module name, or null when that page isn't built yet. */
export function resolvePage(name: string, loaders: PageLoaders = PAGE_LOADERS): LazyExoticComponent<ComponentType<ConsolePageProps>> | null {
    const load = loaders[`./pages/${name}.tsx`];
    if (!load) return null;
    const cacheKey = loaders === PAGE_LOADERS ? name : '';
    if (cacheKey && lazyPages.has(cacheKey)) return lazyPages.get(cacheKey)!;
    const page = lazy(() => load() as Promise<PageModule>);
    if (cacheKey) lazyPages.set(cacheKey, page);
    return page;
}
