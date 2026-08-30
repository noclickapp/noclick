/**
 * Unified Settings component with sidebar navigation.
 * Consolidates Usage Dashboard and Organization Settings into a single view.
 * Organization section only appears when user is in an organization context.
 * On mobile: shows a menu landing page first; tapping an item drills into that section.
 * On desktop: classic left sidebar + content layout.
 */

import { useEffect, useState, lazy, Suspense } from 'react';
import { ArrowLeft, BarChart3, Bell, Brain, Building2, ChevronRight, Code2, KeyRound, Eye, Plug } from 'lucide-react';
import { cn } from '~/lib/utils';
import { ShortcutTooltip } from '~/components/shared/ShortcutTooltip';
import { COMMAND_SHORTCUT_KEYS } from '~/lib/shortcuts';
import { useOrgContext } from '~/hooks/useOrgContext';
import { useValtioState } from '~/hooks/useValtioState';
import { useIsMobile } from '~/hooks/useIsMobile';
import { useUrlSyncedTab } from '~/hooks/useUrlSyncedTab';
import { navigateToTab, SETTINGS_SECTIONS, type SettingsSection } from '~/lib/navigation';
import { UsageDashboard } from '~/components/usage/UsageDashboard';
import { OrganizationSettings } from '~/components/organization/OrganizationSettings';
import { CredentialsSettings } from '~/components/settings/CredentialsSettings';
import { DeveloperSettings } from '~/components/settings/DeveloperSettings';
import { InstanceOAuthSettings } from '~/components/settings/InstanceOAuthSettings';
import { InstanceProviderKeysSettings } from '~/components/settings/InstanceProviderKeysSettings';
import { NotificationsSettings } from '~/components/settings/NotificationsSettings';
import { PopupPreferencesSettings } from '~/components/settings/PopupPreferencesSettings';
import { isLocalEdition } from '~/lib/edition';
// Lazy: the Skills section embeds workflow canvases (SkillEditor → FlowCanvas and
// SkillRowExpansion → ReadOnlyFlowCanvas), which pull the node-component registry
// (~4.7MB). Settings is always mounted on the dashboard, so loading Skills eagerly
// dragged that whole graph into the dashboard's initial bundle. It now loads only
// when the Skills tab is opened.
const SkillsSettings = lazy(() =>
    import('~/components/settings/SkillsSettings').then(m => ({ default: m.SkillsSettings }))
);

interface SettingsProps {
  initialSection?: SettingsSection;
  onNavigateBack?: () => void;
}

export function Settings({ initialSection, onNavigateBack }: SettingsProps) {
  const [orgContext] = useOrgContext();
  const hasOrg = !!orgContext.id;
  const isPersonalWorkspace = orgContext.isPersonalWorkspace;
  const [personalWsOrgId] = useValtioState<string | null>('global', 'personal_workspace_org_id', null);
  // Organization ID for the members/org settings panel
  // In org context: use the org ID. In personal workspace: use the personal workspace org ID.
  const settingsOrgId = hasOrg ? orgContext.id! : personalWsOrgId;
  const isMobile = useIsMobile(640);

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

  const handleNavigateBack = () => {
    if (onNavigateBack) {
      onNavigateBack();
    } else {
      navigateToTab('flow');
    }
  };

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
      label: hasOrg ? 'Organization' : 'Members',
      description: hasOrg ? 'Manage your team and organization' : 'Invite members to your workspace',
      icon: Building2,
      visible: hasOrg || !!personalWsOrgId,
    },
    {
      id: 'skills' as const,
      label: 'Skills',
      description: 'Reusable agent context — text and workflows',
      icon: Brain,
      visible: true,
    },
    {
      id: 'notifications' as const,
      label: 'Notifications',
      description: 'Email alerts for failures, credits, and digests',
      icon: Bell,
      visible: true,
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
      description: 'API keys for external SDK access',
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
  ].filter(item => item.visible);

  // Which section is currently active (mobile: mobileSection, desktop: activeSection)
  const currentSection = isMobile ? mobileSection : activeSection;

  // ── Mobile menu landing page ──────────────────────────────────────────────
  if (isMobile && mobileSection === null) {
    return (
      <div className="flex flex-col h-full bg-background">
        {/* Top bar */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border dark:border-white/[0.06] flex-shrink-0">
          <button
            onClick={handleNavigateBack}
            className="flex items-center justify-center w-8 h-8 text-muted-foreground dark:text-white/40 hover:text-foreground/80 hover:bg-foreground/[0.05] rounded-full transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <h1 className="text-lg font-semibold text-foreground tracking-tight">Settings</h1>
        </div>

        {/* Menu items */}
        <div className="flex-1 overflow-y-auto px-3 py-4 space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                onClick={() => setMobileSection(item.id)}
                className="w-full flex items-center gap-4 px-4 py-4 rounded-2xl bg-foreground/[0.04] hover:bg-foreground/[0.07] border border-border dark:border-white/[0.06] transition-colors text-left"
              >
                <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-foreground/[0.06] flex-shrink-0">
                  <Icon className="w-5 h-5 text-muted-foreground dark:text-white/70" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-foreground">{item.label}</p>
                  <p className="text-xs text-muted-foreground dark:text-white/40 mt-0.5">{item.description}</p>
                </div>
                <ChevronRight className="w-4 h-4 text-muted-foreground/70 dark:text-white/30 flex-shrink-0" />
              </button>
            );
          })}
        </div>
      </div>
    );
  }

  // ── Mobile section detail view ────────────────────────────────────────────
  if (isMobile && mobileSection !== null) {
    const activeItem = navItems.find(item => item.id === mobileSection);
    return (
      <div className="flex flex-col h-full bg-background">
        {/* Top bar with back-to-menu */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border dark:border-white/[0.06] flex-shrink-0">
          <button
            onClick={() => setMobileSection(null)}
            className="flex items-center justify-center w-8 h-8 text-muted-foreground dark:text-white/40 hover:text-foreground/80 hover:bg-foreground/[0.05] rounded-full transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <h1 className="text-base font-semibold text-foreground tracking-tight">
            {activeItem?.label ?? 'Settings'}
          </h1>
        </div>

        {/* Section content */}
        <div className="flex-1 overflow-y-auto scrollbar-subtle">
          <div className="p-4">
            {mobileSection === 'usage' && <UsageDashboard embedded />}
            {mobileSection === 'credentials' && <CredentialsSettings embedded />}
            {mobileSection === 'skills' && (
              <Suspense fallback={<div className="h-40" />}>
                <SkillsSettings />
              </Suspense>
            )}
            {mobileSection === 'developer' && <DeveloperSettings />}
            {mobileSection === 'oauth-apps' && (
              <>
                <InstanceProviderKeysSettings />
                <InstanceOAuthSettings />
              </>
            )}
            {mobileSection === 'notifications' && <NotificationsSettings />}
            {mobileSection === 'popups' && <PopupPreferencesSettings />}
            {mobileSection === 'organization' && settingsOrgId && (
              <OrganizationSettings organizationId={settingsOrgId} embedded isPersonalWorkspace={isPersonalWorkspace} />
            )}
          </div>
        </div>
      </div>
    );
  }

  // ── Desktop layout: sidebar + content ────────────────────────────────────
  return (
    <div className="flex h-full">
      {/* Sidebar */}
      <div className="w-56 flex-shrink-0">
        <div className="p-5 pt-6">
          <div className="flex items-center gap-3 mb-8">
            <button
              onClick={handleNavigateBack}
              className="flex items-center justify-center w-10 h-10 text-muted-foreground dark:text-white/40 hover:text-foreground/80 hover:bg-foreground/[0.05] rounded-full transition-colors"
            >
              <ArrowLeft className="w-5 h-5" />
            </button>
            <h1 className="text-xl font-semibold text-foreground tracking-tight">Settings</h1>
          </div>

          <nav className="space-y-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = activeSection === item.id;
              const keys = COMMAND_SHORTCUT_KEYS[`nav:settings:${item.id}`]?.keys;
              return (
                <ShortcutTooltip key={item.id} keys={keys} side="right">
                  <button
                    onClick={() => setActiveSection(item.id)}
                    className={cn(
                      "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-[0.9375rem] font-medium transition-all duration-150",
                      isActive
                        ? "bg-foreground/[0.08] text-accent-foreground"
                        : "text-muted-foreground dark:text-white/50 hover:text-foreground/80 hover:bg-foreground/[0.04]"
                    )}
                  >
                    <Icon className={cn(
                      "w-[18px] h-[18px]",
                      isActive ? "text-foreground/90" : "text-muted-foreground dark:text-white/40"
                    )} />
                    <span>{item.label}</span>
                  </button>
                </ShortcutTooltip>
              );
            })}
          </nav>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto scrollbar-subtle flex flex-col">
        <div className="p-8 pt-6 flex-1">
          {currentSection === 'usage' && <UsageDashboard embedded />}
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
          {currentSection === 'popups' && <PopupPreferencesSettings />}
          {currentSection === 'organization' && settingsOrgId && (
            <OrganizationSettings organizationId={settingsOrgId} embedded isPersonalWorkspace={isPersonalWorkspace} />
          )}
        </div>
      </div>
    </div>
  );
}
