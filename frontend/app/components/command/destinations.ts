// Every place in the app the command palette can go, derived from the tables the pages themselves read: the shell's
// pages (SHELL_PAGES), each Resources kind and its page for getting one (KINDS), each Settings section the account
// sees (SETTINGS_SECTION_DEFS), Connections' tabs (CONNECTIONS_VIEWS) and Automations' Trash. The open edition runs
// the tabbed layout instead of the shell's pages.
import { LayoutDashboard, LayoutGrid, Settings, Trash2, UserCheck } from 'lucide-react';
import type { VisibleSettingsSection } from '~/components/settings/sections';
import { connectionsAddress, connectionsViews } from '~/components/shell/connections/views';
import { SHELL_PAGES } from '~/components/shell/pages';
import { resourceAddress, type KindDef } from '~/components/shell/resources/kinds';
import { goToWorkflows, navigateToDashboard, navigateToSettings, navigateToTab, triggerBrowserAction, type DashboardTab } from '~/lib/navigation';
import type { PaletteEntry } from './sources';

export interface DestinationContext {
    /** The app shell's pages; else the open edition's tabbed layout. */
    shell: boolean;
    /** The Resources kinds this instance has (`visibleKinds`). */
    kinds: readonly KindDef[];
    /** The instance bills, so what's bought (numbers, domains) can be bought by hand. */
    billing: boolean;
    inOrganization: boolean;
    /** The Settings sections the account sees, less those the host shows as pages of their own. */
    settings: readonly VisibleSettingsSection[];
}

// Pages whose bare address would keep where you were inside them: going to the page means its top.
const PAGE_ADDRESS: Partial<Record<DashboardTab, Record<string, string | null>>> = {
    resources: resourceAddress(null),
    connections: connectionsAddress('all'),
};

// The open edition's tabbed layout (its NavBar), which has none of the shell's pages.
const TABBED_PAGES: PaletteEntry[] = [
    { id: 'nav:workflows', label: 'Workflows', icon: LayoutGrid, keywords: 'home browser flows automations', browse: true, run: goToWorkflows },
    { id: 'nav:dashboard', label: 'Dashboard', icon: LayoutDashboard, keywords: 'home overview feed runs agents files credentials', browse: true, run: () => navigateToDashboard() },
    { id: 'nav:attention', label: 'Needs you', icon: UserCheck, keywords: 'approvals feed notifications inbox questions', browse: true, run: () => navigateToDashboard('attention') },
    { id: 'nav:settings', label: 'Settings', icon: Settings, keywords: 'preferences account', browse: true, run: () => navigateToSettings() },
];

export function appDestinations(ctx: DestinationContext): PaletteEntry[] {
    const pages: PaletteEntry[] = ctx.shell
        ? SHELL_PAGES.map((p) => ({
              id: `nav:${p.id === 'flow' ? 'workflows' : p.id}`,
              label: p.label,
              icon: p.icon,
              keywords: p.keywords,
              browse: true,
              // The flow reset closes any open workflow so it lands on the browser.
              run: p.id === 'flow' ? goToWorkflows : () => navigateToTab(p.id, PAGE_ADDRESS[p.id]),
          }))
        : TABBED_PAGES;

    const trash: PaletteEntry = {
        id: 'nav:trash',
        label: 'Trash',
        context: ctx.shell ? 'Automations' : 'Workflows',
        icon: Trash2,
        keywords: 'deleted removed restore bin',
        run: () => triggerBrowserAction('trash'),
    };

    const kinds: PaletteEntry[] = ctx.shell
        ? ctx.kinds.flatMap((k) => {
              const list: PaletteEntry = {
                  id: `nav:resources:${k.id}`,
                  label: k.label,
                  context: 'Resources',
                  icon: k.icon,
                  keywords: k.keywords,
                  about: k.empty,
                  run: () => navigateToTab('resources', resourceAddress(k.id)),
              };
              if (!k.manual || (k.manual.bought && !ctx.billing)) return [list];
              const manual: PaletteEntry = {
                  id: `nav:resources:${k.id}:new`,
                  label: k.manual.label,
                  context: 'Resources',
                  icon: k.icon,
                  keywords: `${k.label} ${k.keywords} get new add buy purchase`,
                  run: () => navigateToTab('resources', resourceAddress(k.id, { manual: true })),
              };
              return [list, manual];
          })
        : [];

    const settings: PaletteEntry[] = ctx.settings.map((s) => ({
        id: `nav:settings:${s.id}`,
        label: s.label,
        context: 'Settings',
        icon: s.icon,
        keywords: s.keywords,
        about: s.description,
        run: () => navigateToSettings({ section: s.id }),
    }));

    const connectionsIcon = SHELL_PAGES.find((p) => p.id === 'connections')!.icon;
    const connections: PaletteEntry[] = ctx.shell
        ? connectionsViews(ctx.inOrganization).map((v) => ({
              id: `nav:connections:${v.id}`,
              label: v.label,
              context: 'Connections',
              icon: connectionsIcon,
              keywords: v.keywords,
              run: () => navigateToTab('connections', connectionsAddress(v.id)),
          }))
        : [];

    return [...pages, ...kinds, trash, ...connections, ...settings];
}
