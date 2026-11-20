// The app shell's pages: one list the sidebar, the command palette and the "G <key>" shortcuts all read, so a page is
// named and ordered in one place. Where a page is (an address, a route) is its host's: the shell names it by its id.
import { BriefcaseBusiness, Layers, MessageCircle, Plug, Settings, Workflow, type LucideIcon } from 'lucide-react';

export type ShellPageId = 'chat' | 'work' | 'flow' | 'connections' | 'resources' | 'settings';

export interface ShellPage {
    id: ShellPageId;
    label: string;
    icon: LucideIcon;
    /** Extra words the command palette matches. What's inside a page (a Resources kind, a Settings section) is a
     *  destination of its own, found by its own words. */
    keywords: string;
}

export const SHELL_PAGES: readonly ShellPage[] = [
    { id: 'chat', label: 'Chat', icon: MessageCircle, keywords: 'home coordinator noclick assistant ask' },
    { id: 'work', label: 'Work', icon: BriefcaseBusiness, keywords: 'channels spaces agents people team dms threads talk conversations' },
    { id: 'flow', label: 'Automations', icon: Workflow, keywords: 'workflows flows browser canvas build' },
    { id: 'connections', label: 'Connections', icon: Plug, keywords: 'credentials accounts integrations oauth keys' },
    { id: 'resources', label: 'Resources', icon: Layers, keywords: 'owned purchases inventory' },
    { id: 'settings', label: 'Settings', icon: Settings, keywords: 'preferences account options' },
];

/** The page an id belongs to; anything else (a host's own pages) has none. */
export function shellPageFor(id: string): ShellPage | undefined {
    return SHELL_PAGES.find((p) => p.id === id);
}
