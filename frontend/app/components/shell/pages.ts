// The app shell's navigation: one list the sidebar, the command palette and the
// "G <key>" shortcuts all read, so a page is named and ordered in one place.
import { Hash, Layers, MessageCircle, Plug, Settings, Workflow, type LucideIcon } from 'lucide-react';
import type { DashboardTab } from '~/lib/navigation';

export interface ShellPage {
    /** The Dashboard tab id (`?tab=` encoding lives in lib/navigation). */
    id: DashboardTab;
    label: string;
    icon: LucideIcon;
    /** Extra words the command palette matches. What's inside a page (a Resources kind, a Settings section) is a
     *  destination of its own, found by its own words. */
    keywords: string;
}

export const SHELL_PAGES: readonly ShellPage[] = [
    { id: 'chat', label: 'Chat', icon: MessageCircle, keywords: 'home coordinator noclick assistant ask' },
    { id: 'channels', label: 'Channels', icon: Hash, keywords: 'agents groups talk conversations team' },
    { id: 'flow', label: 'Automations', icon: Workflow, keywords: 'workflows flows browser canvas build' },
    { id: 'connections', label: 'Connections', icon: Plug, keywords: 'credentials accounts integrations oauth keys' },
    { id: 'resources', label: 'Resources', icon: Layers, keywords: 'owned purchases inventory' },
    { id: 'settings', label: 'Settings', icon: Settings, keywords: 'preferences account options' },
];

/** The page a tab id belongs to; debug and analytics have none. */
export function shellPageFor(tab: string): ShellPage | undefined {
    return SHELL_PAGES.find((p) => p.id === tab);
}
