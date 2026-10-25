// Settings' sections: one table that Settings lists and the command palette jumps to, with who sees each.
import { useMemo } from 'react';
import { BarChart3, Bell, Brain, Building2, Code2, Eye, KeyRound, Plug, Smartphone, type LucideIcon } from 'lucide-react';
import { useInstanceCapabilities } from '~/hooks/useInstanceCapabilities';
import { useOrgContext } from '~/hooks/useOrgContext';
import { usePhoneLinkingAvailable } from '~/hooks/usePhoneLinking';
import { useValtioState } from '~/hooks/useValtioState';
import { isLocalEdition } from '~/lib/edition';
import type { SettingsSection } from '~/lib/navigation';

/** What decides whether a section shows. */
interface SectionContext {
    /** Plans and top-ups exist on this instance. */
    billing: boolean;
    /** In an organization, rather than the personal workspace. */
    inOrganization: boolean;
    /** The workspace has members to show (an organization, or a personal workspace that has one). */
    hasMembers: boolean;
    phoneLinking: boolean;
    selfHosted: boolean;
}

export interface SettingsSectionDef {
    id: SettingsSection;
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
        id: 'credentials',
        label: 'Credentials',
        description: 'Manage API keys and connected accounts',
        icon: KeyRound,
        keywords: 'connections accounts oauth integrations api keys',
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
    {
        id: 'oauth-apps',
        label: 'Self-hosted',
        description: 'The builder key, texting and OAuth apps for this instance',
        icon: Plug,
        keywords: 'instance keys oauth apps smtp email provider texting whatsapp imessage sendblue',
        // The hosted service connects through its own registered apps; this is the self-hosted alternative to
        // editing two .env files by hand.
        shown: (c) => c.selfHosted,
    },
];

/** The section list's groups, in order; a section shows in the first that names it. */
export const SETTINGS_GROUPS: readonly { label: string; sections: readonly SettingsSection[] }[] = [
    { label: 'Workspace', sections: ['usage', 'organization'] },
    { label: 'Preferences', sections: ['notifications', 'phone', 'popups'] },
    { label: 'Build', sections: ['skills', 'credentials', 'developer', 'oauth-apps'] },
];

export interface VisibleSettingsSection extends Omit<SettingsSectionDef, 'description' | 'shown'> {
    description: string;
}

const NONE: readonly SettingsSection[] = [];

/** The sections this account sees, less the `hidden` ones its host shows as pages of their own. */
export function useSettingsSections(hidden: readonly SettingsSection[] = NONE): VisibleSettingsSection[] {
    const [orgContext] = useOrgContext();
    const [personalWsOrgId] = useValtioState<string | null>('global', 'personal_workspace_org_id', null);
    const { billing } = useInstanceCapabilities();
    const phoneLinking = usePhoneLinkingAvailable();
    const inOrganization = !!orgContext.id;
    const hasMembers = inOrganization || !!personalWsOrgId;
    return useMemo(() => {
        const context: SectionContext = { billing, inOrganization, hasMembers, phoneLinking, selfHosted: isLocalEdition() };
        return SETTINGS_SECTION_DEFS.filter((s) => (s.shown?.(context) ?? true) && !hidden.includes(s.id)).map((s) => ({
            id: s.id,
            label: s.label,
            icon: s.icon,
            keywords: s.keywords,
            description: typeof s.description === 'function' ? s.description(context) : s.description,
        }));
    }, [billing, inOrganization, hasMembers, phoneLinking, hidden]);
}
