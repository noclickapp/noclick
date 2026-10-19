/**
 * Settings: one page, its sections listed in groups in a column of their own
 * beside the open one on a laptop (rows like the app sidebar's). On a phone the
 * list is the page and a section opens over it, the shell's bar going back. The
 * organization section only appears in an organization or a personal workspace
 * that has one.
 */

import { useEffect, useState, lazy, Suspense } from 'react';
import { BarChart3, Bell, Brain, Building2, ChevronRight, Code2, KeyRound, Eye, Plug, Smartphone } from 'lucide-react';
import { cn } from '~/lib/utils';
import { HAIRLINE } from '~/components/dashboard/primitives';
import { ShortcutTooltip } from '~/components/shared/ShortcutTooltip';
import { COMMAND_SHORTCUT_KEYS } from '~/lib/shortcuts';
import { useOrgContext } from '~/hooks/useOrgContext';
import { useValtioState } from '~/hooks/useValtioState';
import { useIsMobile } from '~/hooks/useIsMobile';
import { useUrlSyncedTab } from '~/hooks/useUrlSyncedTab';
import { SETTINGS_SECTIONS, type SettingsSection } from '~/lib/navigation';
import { PhoneBarBack, useInPhoneShell } from '~/components/shell/AppShell';
import { SidebarItem } from '~/components/shell/AppSidebar';
import { UsagePage } from '~/components/usage/page/UsagePage';
import { OrganizationSettings } from '~/components/organization/OrganizationSettings';
import { CredentialsSettings } from '~/components/settings/CredentialsSettings';
import { DeveloperSettings } from '~/components/settings/DeveloperSettings';
import { InstanceOAuthSettings } from '~/components/settings/InstanceOAuthSettings';
import { InstanceProviderKeysSettings } from '~/components/settings/InstanceProviderKeysSettings';
import { NotificationsSettings } from '~/components/settings/NotificationsSettings';
import { PhoneSettings } from '~/components/settings/PhoneSettings';
import { PopupPreferencesSettings } from '~/components/settings/PopupPreferencesSettings';
import { isLocalEdition } from '~/lib/edition';
import { usePhoneLinkingAvailable } from '~/hooks/usePhoneLinking';
import { DISPLAY, PAGE_TITLE } from '~/components/shell/titles';
// Lazy: the Skills section embeds workflow canvases (SkillEditor → FlowCanvas and
// SkillRowExpansion → ReadOnlyFlowCanvas), which pull the node-component registry
// (~4.7MB). Settings is always mounted on the dashboard, so loading Skills eagerly
// dragged that whole graph into the dashboard's initial bundle. It now loads only
// when the Skills tab is opened.
const SkillsSettings = lazy(() =>
    import('~/components/settings/SkillsSettings').then(m => ({ default: m.SkillsSettings }))
);

/** The section list's groups, in order; a section shows in the first that names it. */
const GROUPS: readonly { label: string; sections: readonly SettingsSection[] }[] = [
  { label: 'Workspace', sections: ['usage', 'organization'] },
  { label: 'Preferences', sections: ['notifications', 'phone', 'popups'] },
  { label: 'Build', sections: ['skills', 'credentials', 'developer', 'oauth-apps'] },
];

interface SettingsProps {
  initialSection?: SettingsSection;
  /** Sections the host shows as pages of their own (the app shell's
   *  Connections and Resources), left out of the section list. */
  hiddenSections?: readonly SettingsSection[];
}

export function Settings({ initialSection, hiddenSections = [] }: SettingsProps) {
  const [orgContext] = useOrgContext();
  const hasOrg = !!orgContext.id;
  const isPersonalWorkspace = orgContext.isPersonalWorkspace;
  const [personalWsOrgId] = useValtioState<string | null>('global', 'personal_workspace_org_id', null);
  // Organization ID for the members/org settings panel
  // In org context: use the org ID. In personal workspace: use the personal workspace org ID.
  const settingsOrgId = hasOrg ? orgContext.id! : personalWsOrgId;
  const inPhone = useInPhoneShell();
  const narrow = useIsMobile(640);
  const isMobile = inPhone || narrow;

  // On mobile, null means "show the menu page"; a value means drill into that section.
  // Only pre-select a section if explicitly deep-linked (i.e. not the default 'usage').
  const [mobileSection, setMobileSection] = useState<SettingsSection | null>(
    initialSection && initialSection !== 'usage' ? initialSection : null
  );

  // Use the standardized hook for URL-synced tab state (drives desktop)
  const [activeSection, setActiveSection] = useUrlSyncedTab<SettingsSection>({
    param: 'section',
    defaultValue: 'usage',
    validValues: [...SETTINGS_SECTIONS],
    initial: initialSection,
    waitFor: initialSection !== 'organization' || hasOrg || !!personalWsOrgId,
    extraParams: { tab: 'settings' },
    clearParamsOn: { usage: ['orgTab'] },
  });

  // If org/workspace section becomes unavailable, reset both
  useEffect(() => {
    if (activeSection === 'organization' && !hasOrg && !personalWsOrgId) {
      setActiveSection('usage');
    }
    if (mobileSection === 'organization' && !hasOrg && !personalWsOrgId) {
      setMobileSection(null);
    }
  }, [activeSection, mobileSection, hasOrg, personalWsOrgId, setActiveSection]);

  const phoneLinking = usePhoneLinkingAvailable();
  const navItems = [
    {
      id: 'usage' as const,
      label: 'Usage',
      description: 'Track AI, compute, and resource costs',
      icon: BarChart3,
      visible: true,
    },
    {
      id: 'credentials' as const,
      label: 'Credentials',
      description: 'Manage API keys and connected accounts',
      icon: KeyRound,
      visible: true,
    },
    {
      id: 'organization' as const,
      label: 'Members',
      description: hasOrg ? 'Who’s in this workspace and how they sign in' : 'Invite people to your workspace',
      icon: Building2,
      visible: hasOrg || !!personalWsOrgId,
    },
    {
      id: 'skills' as const,
      label: 'Skills',
      description: 'Reusable agent context: text and workflows',
      icon: Brain,
      visible: true,
    },
    {
      id: 'notifications' as const,
      label: 'Notifications',
      description: 'Email alerts for failures, your balance, and digests',
      icon: Bell,
      visible: true,
    },
    {
      id: 'phone' as const,
      label: 'Phone',
      description: 'Link your number for WhatsApp and calls',
      icon: Smartphone,
      visible: phoneLinking,
    },
    {
      id: 'popups' as const,
      label: 'Popups',
      description: 'Choose which in-app popups and banners appear',
      icon: Eye,
      visible: true,
    },
    {
      id: 'developer' as const,
      label: 'Developer',
      description: 'API keys and the SDKs',
      icon: Code2,
      visible: true,
    },
    {
      id: 'oauth-apps' as const,
      label: 'Self-hosted',
      description: 'The builder key and OAuth apps for this instance',
      icon: Plug,
      // The hosted service connects through its own registered apps; this is
      // the self-hosted alternative to editing two .env files by hand.
      visible: isLocalEdition(),
    },
  ].filter(item => item.visible && !hiddenSections.includes(item.id));
  const groups = GROUPS.map((g) => ({ label: g.label, items: navItems.filter((item) => g.sections.includes(item.id)) })).filter((g) => g.items.length);

  const renderSection = (currentSection: SettingsSection | null) => (
    <>
      {currentSection === 'usage' && <UsagePage />}
      {currentSection === 'credentials' && <CredentialsSettings embedded />}
      {currentSection === 'skills' && (
        <Suspense fallback={<div className="h-40" />}>
          <SkillsSettings />
        </Suspense>
      )}
      {currentSection === 'developer' && <DeveloperSettings />}
      {currentSection === 'oauth-apps' && (
        <>
          <InstanceProviderKeysSettings />
          <InstanceOAuthSettings />
        </>
      )}
      {currentSection === 'notifications' && <NotificationsSettings />}
      {currentSection === 'phone' && <PhoneSettings />}
      {currentSection === 'popups' && <PopupPreferencesSettings />}
      {currentSection === 'organization' && settingsOrgId && (
        <OrganizationSettings organizationId={settingsOrgId} embedded isPersonalWorkspace={isPersonalWorkspace} />
      )}
    </>
  );

  // ── Phone: the sections as one list ───────────────────────────────────────
  if (isMobile && mobileSection === null) {
    return (
      <div className="h-full overflow-y-auto scrollbar-subtle">
        <div className="mx-auto w-full max-w-[640px] px-4 pb-24 pt-3">
          {!inPhone && <h1 className={cn('mb-5', PAGE_TITLE, 'text-[30px]')}>Settings</h1>}
          <div className="space-y-6">
            {groups.map((group) => (
              <section key={group.label}>
                <h2 className="mb-2 px-1 text-[12.5px] font-medium text-muted-foreground">{group.label}</h2>
                <div className={cn('divide-y overflow-hidden rounded-2xl border bg-card dark:divide-foreground/[0.06] dark:bg-transparent', HAIRLINE)}>
                  {group.items.map((item) => {
                    const Icon = item.icon;
                    return (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => setMobileSection(item.id)}
                        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-foreground/[0.03] focus-visible:bg-foreground/[0.03] focus-visible:outline-none"
                      >
                        <Icon className="h-5 w-5 shrink-0 text-foreground/75" strokeWidth={1.6} />
                        <span className="min-w-0 flex-1">
                          <span className="block text-[15px] text-foreground">{item.label}</span>
                          <span className="block truncate text-[13px] text-muted-foreground">{item.description}</span>
                        </span>
                        <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/60" />
                      </button>
                    );
                  })}
                </div>
              </section>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // ── Phone: one section, the bar going back to the list ─────────────────────
  if (isMobile && mobileSection !== null) {
    return (
      <div className="h-full overflow-y-auto scrollbar-subtle">
        <PhoneBarBack label="Settings" onBack={() => setMobileSection(null)} />
        <div className="px-4 pb-24 pt-3">
          {!inPhone && (
            <button
              type="button"
              onClick={() => setMobileSection(null)}
              className="-ml-1 mb-4 inline-flex items-center gap-0.5 rounded-md px-1 py-0.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
            >
              <ChevronRight className="h-3.5 w-3.5 rotate-180" />
              Settings
            </button>
          )}
          {renderSection(mobileSection)}
        </div>
      </div>
    );
  }

  // ── Laptop: the sections in their column beside the open one ─────────────
  return (
    <div className="flex h-full">
      <nav aria-label="Settings" className={cn('flex w-[248px] shrink-0 flex-col border-r', HAIRLINE)}>
        <div className="flex h-14 shrink-0 items-center px-5">
          <h1 className={cn(DISPLAY, 'text-[26px] leading-none text-foreground')}>Settings</h1>
        </div>
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-2 pb-8 pt-1 scrollbar-subtle">
          {groups.map((group) => (
            <div key={group.label}>
              <p className="px-3 pb-1.5 text-[12.5px] font-medium text-muted-foreground">{group.label}</p>
              <div className="flex flex-col gap-0.5">
                {group.items.map((item) => {
                  const keys = COMMAND_SHORTCUT_KEYS[`nav:settings:${item.id}`]?.keys;
                  return (
                    <ShortcutTooltip key={item.id} keys={keys} side="right">
                      <div>
                        <SidebarItem label={item.label} icon={item.icon} current={activeSection === item.id} collapsed={false} onSelect={() => setActiveSection(item.id)} />
                      </div>
                    </ShortcutTooltip>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </nav>

      <div className="min-w-0 flex-1 overflow-y-auto scrollbar-subtle">
        <div className="mx-auto w-full max-w-[880px] px-10 pb-24 pt-10">{renderSection(activeSection)}</div>
      </div>
    </div>
  );
}
