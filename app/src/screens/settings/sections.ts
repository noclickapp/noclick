// Settings' sections: one table that Settings lists and the command palette jumps to, with who sees each, and the
// groups the list shows them in. Whoever draws Settings says what it knows of the account (`SectionContext`); which
// sections show follows from that alone (`visibleSections`).
import { BarChart3, Bell, Brain, Building2, Code2, CreditCard, Eye, Smartphone, type LucideIcon } from 'lucide-react';

/** A section's id, as the address's `?section=` names it. */
export type SettingsSectionId = 'usage' | 'billing' | 'organization' | 'skills' | 'notifications' | 'phone' | 'popups' | 'developer';

/** What decides whether a section shows. */
export interface SectionContext {
    /** In an organization, rather than the personal workspace. */
    inOrganization: boolean;
    /** The workspace has members to show (an organization, or a personal workspace that has one). */
    hasMembers: boolean;
    phoneLinking: boolean;
}

export interface SettingsSectionDef {
    id: SettingsSectionId;
    label: string;
    description: string | ((c: SectionContext) => string);
    icon: LucideIcon;
    /** Other words people use for it, which the command palette matches. */
    keywords: string;
    /** Shown only where this holds; always otherwise. */
    shown?: (c: SectionContext) => boolean;
}

export const SETTINGS_SECTION_DEFS: readonly SettingsSectionDef[] = [
    {
        id: 'usage',
        label: 'Usage',
        description: 'Track AI, compute, and resource costs',
        icon: BarChart3,
        keywords: 'costs spend spending credits money',
    },
    {
        id: 'billing',
        label: 'Plan and billing',
        description: 'Your plan, balance and monthly spending cap',
        icon: CreditCard,
        keywords: 'plan billing balance subscription upgrade payment invoices funds top up spending cap limit',
    },
    {
        id: 'organization',
        label: 'Members',
        description: (c) => (c.inOrganization ? 'Who’s in this workspace and how they sign in' : 'Invite people to your workspace'),
        icon: Building2,
        keywords: 'members team people invite workspace organization sso',
        shown: (c) => c.hasMembers,
    },
    {
        id: 'skills',
        label: 'Skills',
        description: 'Reusable agent context: text and workflows',
        icon: Brain,
        keywords: 'agent context knowledge',
    },
    {
        id: 'notifications',
        label: 'Notifications',
        description: 'Email alerts for failures, your balance, and digests',
        icon: Bell,
        keywords: 'alerts emails digest',
    },
    {
        id: 'phone',
        label: 'Phone',
        description: 'Link your number for WhatsApp and calls',
        icon: Smartphone,
        keywords: 'my phone link number whatsapp mobile',
        shown: (c) => c.phoneLinking,
    },
    {
        id: 'popups',
        label: 'Popups',
        description: 'Choose which in-app popups and banners appear',
        icon: Eye,
        keywords: 'banners tips hints',
    },
    {
        id: 'developer',
        label: 'Developer',
        description: 'API keys and the SDKs',
        icon: Code2,
        keywords: 'api key api keys token sdk',
    },
];

/** The section list's groups, in order; a section shows in the first that names it. */
export const SETTINGS_GROUPS: readonly { label: string; sections: readonly SettingsSectionId[] }[] = [
    { label: 'Workspace', sections: ['usage', 'billing', 'organization'] },
    { label: 'Preferences', sections: ['notifications', 'phone', 'popups'] },
    { label: 'Build', sections: ['skills', 'developer'] },
];

export interface VisibleSettingsSection extends Omit<SettingsSectionDef, 'description' | 'shown'> {
    description: string;
}

/** The sections an account in `context` sees, less the `hidden` ones its host shows as pages of their own. */
export function visibleSections(context: SectionContext, hidden: readonly string[] = []): VisibleSettingsSection[] {
    return SETTINGS_SECTION_DEFS.filter((s) => (s.shown?.(context) ?? true) && !hidden.includes(s.id)).map((s) => ({
        id: s.id,
        label: s.label,
        icon: s.icon,
        keywords: s.keywords,
        description: typeof s.description === 'function' ? s.description(context) : s.description,
    }));
}

export interface SectionGroup {
    label: string;
    items: VisibleSettingsSection[];
}

/** `sections` in the list's groups, a group with none of them left out. */
export function groupSections(sections: readonly VisibleSettingsSection[]): SectionGroup[] {
    return SETTINGS_GROUPS.map((g) => ({ label: g.label, items: sections.filter((item) => g.sections.includes(item.id)) })).filter((g) => g.items.length);
}
