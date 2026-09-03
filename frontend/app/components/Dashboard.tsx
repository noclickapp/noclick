import { useEffect, useLayoutEffect, useState, useCallback, useRef, lazy, Suspense } from 'react';
import { useSearchParams } from 'react-router';
import { NavBar } from '~/components/nav/NavBar';
import { NoClick } from '~/components/chat/NoClick';
import { SetupHandoffCover } from '~/components/workflow/setup/SetupHandoffCover';
import { useValtioState } from '~/hooks/useValtioState';
import { useCachedValtioState } from '~/hooks/useCachedValtioState';
import { useOrgContext } from '~/hooks/useOrgContext';
import { setPendingNodeSelection } from '~/components/workflow/WorkflowContext';
import { updateBuilderContext } from '~/lib/builder-context';
import { POST_ONBOARDING_FLOW_KEY, clearPostOnboardingFlow } from '~/lib/deferredOpen';
import { useGlobalKeys } from '~/hooks/useGlobalKeys';
import { useLeaderShortcuts } from '~/hooks/useLeaderShortcuts';
import { isTextEntryTarget } from '~/lib/keyboard';
import { useIsMobile } from '~/hooks/useIsMobile';
import { useDebugToolsEnabled } from '~/hooks/useDebugToolsEnabled';
import { profilingStore } from '~/lib/profiling-store';
import { OnboardingProvider } from '~/hooks/useOnboarding';
import { ChatDrawerProvider } from '~/components/chat/drawer/ChatDrawerProvider';
import { WorkflowBrowserDataProvider } from '~/hooks/WorkflowBrowserDataProvider';
import { CommandPalette } from '~/components/command/CommandPalette';
import { GlobalCreateCredentialDialog } from '~/components/shared/popups/CreateCredentialDialog';
import { WorkflowBrowser } from '~/components/workflow/WorkflowBrowser';
// Lazy: the operator debug tab is rendered only on demand so its static graph
// does not enter the dashboard's initial bundle.
const DebugViewer = lazy(() => import('~/components/debug/DebugViewer').then(m => ({ default: m.DebugViewer })));
// Lazy: the Dashboard tab's chart + credential-icon closure stays out of the initial bundle.
const DashboardTab = lazy(() => import('~/components/dashboard/DashboardTab').then(m => ({ default: m.DashboardTab })));
import { useApprovalCount } from '~/hooks/useApprovalCount';
import { Settings } from '~/components/settings/Settings';
import { getDefaultPanelWidth } from '~/lib/constants';
import { createTabSwitchHandler, applyTabToSearchParams, SETTINGS_SECTIONS, type SettingsSection } from '~/lib/navigation';
import { MessageCircle, LayoutGrid } from 'lucide-react';
import { cn } from '~/lib/utils';

interface DashboardProps {
    user: {
        email: string;
        avatar_url?: string;
        created_at?: string;
        subscription_tier?: 'free' | 'plus' | 'pro' | 'enterprise';
    };
    valtio_path: string;
}

  function DashboardContent({ user, valtio_path }: DashboardProps) {
      // Check for post-onboarding flag to determine initial sidebar state
      // This prevents flicker by starting with sidebar closed if coming from onboarding
      const isPostOnboarding = typeof window !== 'undefined' &&
          sessionStorage.getItem(POST_ONBOARDING_FLOW_KEY) === 'true';

      const [isChatExpanded, setIsChatExpanded] = useCachedValtioState<boolean>(
          'dashboard',
        'isChatExpanded',
        false, // Start closed by default
        true   // skipRedisSync — sidebar state is per-browser, no backend sync needed
    );

    // Skip the sidebar's width animation when opened via the "/" key (keyboard
    // actions are instant); clicking the collapsed bar still animates. Cleared
    // whenever the sidebar closes so the next click-open animates again.
    const [chatNoAnim, setChatNoAnim] = useState(false);
    useEffect(() => {
        if (!isChatExpanded) setChatNoAnim(false);
    }, [isChatExpanded]);
    const [chatWidth, setChatWidth] = useValtioState<number>(
        valtio_path,
        'chatWidth',
        getDefaultPanelWidth()
    );
    const [isDragging, setIsDragging] = useValtioState<boolean>(
        valtio_path,
        'isDragging',
        false
    );
    const [selectedTab, setSelectedTab] = useValtioState<string>(
        valtio_path,
        'selectedTab',
        'flow'
    );

    // Get current org context from cached state
    const [orgContext] = useOrgContext();

    // Create org-aware path suffix for caching workflows/databases per org context
    // This ensures each org (or personal) context has its own cached data
    const orgPathSuffix = orgContext.id ? `org_${orgContext.id}` : 'personal';

    // Scope id for the workflow-browser store: 'org_<id>' | 'personal'. The store
    // keys every fetch/mutation/cache entry off this, so each org's data is fully
    // isolated. Shared by WorkflowBrowserDataProvider + WorkflowBrowser.
    const browserScopeId = orgPathSuffix;

    // Read URL params for tab navigation (supports: databases, workflows, debug)
    const [searchParams, setSearchParams] = useSearchParams();
    const urlTab = searchParams.get('tab');
    const urlWorkflowId = searchParams.get('workflow');
    const urlNodeId = searchParams.get('node');
    const urlFieldKey = searchParams.get('field');

    // Read section param for settings navigation
    const urlSection = searchParams.get('section');

    // Set pending node selection from deep link URL params (run once on mount)
    const deepLinkHandledRef = useRef(false);
    useEffect(() => {
        if (!deepLinkHandledRef.current && urlWorkflowId && urlNodeId) {
            deepLinkHandledRef.current = true;
            setPendingNodeSelection(urlWorkflowId, urlNodeId, urlFieldKey || undefined);
        }
    }, [urlWorkflowId, urlNodeId, urlFieldKey]);

    // Sync URL tab param with selectedTab state (workflow param managed by WorkflowBrowser)
    useEffect(() => {
        if (urlTab === 'workflows') {
            setSelectedTab('flow');
        } else if (urlTab === 'debug') {
            setSelectedTab('debug');
        } else if (urlTab === 'dashboard' || urlTab === 'feed') {
            // 'feed' is the pre-Dashboard name; old links and bookmarks still land here.
            setSelectedTab('dashboard');
        } else if (urlTab === 'settings' || urlTab === 'usage' || urlTab === 'org-settings') {
            // All settings-related tabs route to unified Settings
            setSelectedTab('settings');
            // Set the initial section based on URL - check section param first, then legacy tab param
            if (urlTab === 'org-settings') {
                setSettingsSection('organization');
            } else if (urlSection && SETTINGS_SECTIONS.includes(urlSection as SettingsSection)) {
                setSettingsSection(urlSection as SettingsSection);
            } else {
                setSettingsSection('usage');
            }
        }
    }, [urlTab, urlSection, setSelectedTab]);

    // Mobile responsiveness. Cutoff is 769 (≤768px = mobile) so iPad Mini
    // portrait (exactly 768) uses the single-column tab layout instead of the
    // desktop push-sidebar, which shrinks the canvas + navbar into a crushed
    // sliver at that width.
    const isMobile = useIsMobile(769);
    const [mobileActiveView, setMobileActiveView] = useState<'chat' | 'dashboard'>('dashboard');

    // Latest values addressable from the always-on mobile-view listeners below
    // without re-subscribing on every render.
    const isMobileRef = useRef(isMobile);
    isMobileRef.current = isMobile;
    const mobileViewRef = useRef(mobileActiveView);
    mobileViewRef.current = mobileActiveView;
    // The view the user was on when a builder <ask> appeared. Restored after
    // they answer/skip — but only when it was the FlowCanvas (dashboard) view,
    // per the "return iff previously there" rule.
    const askPrevViewRef = useRef<'chat' | 'dashboard' | null>(null);

    // Feature gates. Debug/Analytics: PostHog `debug` flag in prod, always on
    // in local dev (PostHog is skipped on localhost).
    const debugToolsEnabled = useDebugToolsEnabled();

    // Global listener for approval feed count — keeps NavBar badge in sync
    useApprovalCount();

    // Redirect away from gated tabs if feature is disabled
    useEffect(() => {
        if (selectedTab === 'debug' && !debugToolsEnabled) {
            setSelectedTab('flow');
        }
    }, [selectedTab, debugToolsEnabled, setSelectedTab]);

    // Socket profiling retains full request/response payloads, so it's off for
    // regular prod users (memory). Anyone who can see the debug tools gets it
    // enabled from mount, so the drawer shows requests retroactively without
    // having to sit open. One-way: never re-disable on a flag flicker.
    useEffect(() => {
        if (debugToolsEnabled) profilingStore.setEnabled(true);
    }, [debugToolsEnabled]);

    // Feed dashboard tab to builder context so headless builder knows current screen
    useEffect(() => {
        updateBuilderContext({ dashboardTab: selectedTab });
    }, [selectedTab]);

    // Handle post-onboarding flow: close sidebar and navigate to workflows tab
    // Using useLayoutEffect to run synchronously before browser paint, preventing visual flicker
    // Note: WorkflowBrowser reads the sessionStorage flag during its initial render to kick off
    // an automatic blank-workflow creation; this effect is just here to force the sidebar closed.
    useLayoutEffect(() => {
        if (isPostOnboarding) {
            // Clear the flag after WorkflowBrowser has captured it (WorkflowBrowser reads it
            // via useRef in its initial render, before this effect runs).
            clearPostOnboardingFlow();

            // Force sidebar closed (in case there was persisted state)
            setIsChatExpanded(false);

            // Navigate to workflows tab
            setSelectedTab('flow');
            setSearchParams((prev) => {
                const newParams = new URLSearchParams(prev);
                newParams.set('tab', 'workflows');
                return newParams;
            }, { replace: true });
        }
    }, []); // Only run once on mount

    // Handle tab changes - update URL while preserving existing params
    const handleTabChange = useCallback((tab: string) => {
        // For flow tab, dispatch event to trigger WorkflowBrowser's back navigation (same as back button)
        if (tab === 'flow') {
            window.dispatchEvent(new CustomEvent('noclick:workflow-browser-reset'));
        }
        setSelectedTab(tab);
        // Preserve existing params while updating tab (shared encoder with the
        // event-based createTabSwitchHandler). Settings section is set by the
        // Settings component, not here.
        setSearchParams((prev) => {
            const newParams = new URLSearchParams(prev);
            applyTabToSearchParams(newParams, tab);
            return newParams;
        }, { replace: true });
    }, [setSelectedTab, setSearchParams]);

    // TODO: moving these key handlers to a separate file might make sense
    // in the near future instead of having them here in Dashboard.tsx
    const handleSlashKey = useCallback(
        (event: KeyboardEvent) => {
            // Bare "/" opens the chat sidebar. Ignore ⌘//Ctrl+/ — that's the
            // command palette's "open keyboard shortcuts" binding, not a sidebar
            // toggle.
            if (event.metaKey || event.ctrlKey) return;

            // Only open chat if the user isn't typing in a field.
            if (!isTextEntryTarget(event.target)) {
                event.preventDefault();
                if (!isChatExpanded) {
                    setChatNoAnim(true); // keyboard open → instant
                    setIsChatExpanded(true);
                }
                // Focus the input, with a small delay to ensure it's available
                setTimeout(() => {
                    const windowWithNoClick = window as Window & { noClickFocusInput?: () => void };
                    if (windowWithNoClick.noClickFocusInput) {
                        windowWithNoClick.noClickFocusInput();
                    }
                }, 20);
            }
        },
        [isChatExpanded, setIsChatExpanded]
    );

    const handleEscapeKey = useCallback(
        (event: KeyboardEvent) => {
            if (isChatExpanded) {
                event.preventDefault();
                setIsChatExpanded(false);
            }
        },
        [isChatExpanded, setIsChatExpanded]
    );

    // Global key bindings
    useGlobalKeys({
        '/': handleSlashKey,
        Escape: handleEscapeKey,
    });

    // "G <key>" go-tos and "O <key>" scoped-palette shortcuts (Linear-style).
    useLeaderShortcuts();

    // Listen for sidebar collapse/expand events from guided tour
    useEffect(() => {
        const handleCollapse = () => setIsChatExpanded(false);
        const handleExpand = () => setIsChatExpanded(true);

        document.addEventListener('noclick:sidebar:collapse', handleCollapse);
        document.addEventListener('noclick:sidebar:expand', handleExpand);

        return () => {
            document.removeEventListener('noclick:sidebar:collapse', handleCollapse);
            document.removeEventListener('noclick:sidebar:expand', handleExpand);
        };
    }, [setIsChatExpanded]);

    // Settings section state (for navigating directly to org settings)
    const [settingsSection, setSettingsSection] = useState<SettingsSection>('usage');

    // Listen for tab switch events from anywhere in the app
    // Uses the standardized handler from navigation utilities
    useEffect(() => {
        const handleTabSwitch = createTabSwitchHandler({
            setSelectedTab,
            setSettingsSection,
            setSearchParams,
        });

        window.addEventListener('noclick:switch-tab', handleTabSwitch);

        // Navigate to a specific workflow node (from approval feed, etc.)
        const handleNavigateToNode = (e: Event) => {
            const { workflowId, nodeId } = (e as CustomEvent).detail;
            setPendingNodeSelection(workflowId, nodeId);
            setSelectedTab('flow');
            setSearchParams(prev => {
                const next = new URLSearchParams(prev);
                next.set('tab', 'workflows');
                next.set('workflow', workflowId);
                next.set('node', nodeId);
                return next;
            });
        };
        window.addEventListener('noclick:navigate-to-node', handleNavigateToNode);

        // Open the Dashboard tab at the needs-you queue. Kept under its historical
        // name: interface components (user-authored dashboard JSX) dispatch it via
        // window.parent.dispatchEvent, so it is a public contract.
        const handleSwitchToFeed = () => {
            setSelectedTab('dashboard');
            setSearchParams(prev => {
                const next = new URLSearchParams(prev);
                applyTabToSearchParams(next, 'dashboard');
                next.set('focus', 'attention');
                return next;
            }, { replace: true });
        };
        window.addEventListener('noclick:switch-to-feed', handleSwitchToFeed);

        return () => {
            window.removeEventListener('noclick:switch-tab', handleTabSwitch);
            window.removeEventListener('noclick:navigate-to-node', handleNavigateToNode);
            window.removeEventListener('noclick:switch-to-feed', handleSwitchToFeed);
        };
    }, [setSelectedTab, setSearchParams]);

    // Mobile chat ↔ dashboard view coordination. Registered once; reads the
    // latest isMobile / current view via refs. Mostly no-ops on desktop (where
    // the chat is a collapsible sidebar, not a separate view) — except a
    // surfaced builder <ask> still expands that sidebar so the question is seen.
    useEffect(() => {
        // Explicit programmatic switch (e.g. builder status pill → chat).
        const handleSetView = (e: Event) => {
            const view = (e as CustomEvent).detail?.view;
            if (view === 'chat' || view === 'dashboard') setMobileActiveView(view);
        };
        // Clicking an inline node/edge card in chat selects + zooms a node on the
        // canvas (FlowCanvas handles the pan). On mobile the canvas is hidden
        // behind the chat view, so reveal it.
        const handleRevealCanvas = () => {
            if (isMobileRef.current) setMobileActiveView('dashboard');
        };
        // A builder <ask> surfaced: the question renders inside the chat, so the
        // user can't see it if the chat is hidden. On desktop the chat is a
        // collapsible sidebar — expand it (BuilderInputBridge fires ask:open once
        // per ask, so this respects a later manual collapse). On mobile the chat
        // is a separate view — jump to it and remember to bring them back.
        const handleAskOpen = () => {
            if (!isMobileRef.current) {
                document.dispatchEvent(new CustomEvent('noclick:sidebar:expand'));
                return;
            }
            if (mobileViewRef.current === 'dashboard') {
                askPrevViewRef.current = 'dashboard';
                setMobileActiveView('chat');
            } else {
                askPrevViewRef.current = null;
            }
        };
        const handleAskClose = () => {
            if (askPrevViewRef.current === 'dashboard') setMobileActiveView('dashboard');
            askPrevViewRef.current = null;
        };
        document.addEventListener('noclick:mobile:set-view', handleSetView);
        document.addEventListener('noclick:workflow:select-node', handleRevealCanvas);
        document.addEventListener('noclick:workflow:select-edge', handleRevealCanvas);
        document.addEventListener('noclick:builder:ask:open', handleAskOpen);
        document.addEventListener('noclick:builder:ask:close', handleAskClose);
        return () => {
            document.removeEventListener('noclick:mobile:set-view', handleSetView);
            document.removeEventListener('noclick:workflow:select-node', handleRevealCanvas);
            document.removeEventListener('noclick:workflow:select-edge', handleRevealCanvas);
            document.removeEventListener('noclick:builder:ask:open', handleAskOpen);
            document.removeEventListener('noclick:builder:ask:close', handleAskClose);
        };
    }, []);

    // Tab content renderer shared between mobile and desktop layouts
    const renderTabContent = () => {
        if (selectedTab === 'debug') {
            return <Suspense fallback={<div className="h-full w-full" />}><DebugViewer /></Suspense>;
        } else if (selectedTab === 'flow') {
            return (
                <WorkflowBrowser
                    scopeId={browserScopeId}
                    initialWorkflowId={urlWorkflowId}
                />
            );
        } else if (selectedTab === 'dashboard') {
            return <Suspense fallback={<div className="h-full w-full" />}><DashboardTab /></Suspense>;
        } else if (selectedTab === 'settings') {
            return (
                <div className="h-full" data-onboarding="settings-view">
                    <Settings
                        initialSection={settingsSection}
                    />
                </div>
            );
        }
        return null;
    };

    return (
        <>
        <OnboardingProvider>
        <ChatDrawerProvider>
        <WorkflowBrowserDataProvider scopeId={browserScopeId}>
            <CommandPalette />
            <GlobalCreateCredentialDialog />
            {/* Template-fork hand-off: covers the dashboard until the
                full-screen Setup onboarding is painted (no chrome flash). */}
            <SetupHandoffCover />
            {isMobile ? (
                // Mobile Layout
                <div className="fixed inset-0 flex flex-col">
                    {/* Chat View - always mounted */}
                    <div className={mobileActiveView === 'chat' ? 'flex-1 flex flex-col overflow-hidden' : 'hidden'}>
                        <NoClick
                            isExpanded={true}
                            onExpandChange={() => {}}
                            onWidthChange={() => {}}
                            onDragChange={setIsDragging}
                            isMobileMode={true}
                            userEmail={user.email}
                            userAvatarUrl={user.avatar_url}
                        />
                    </div>

                    {/* Dashboard View - always mounted */}
                    <div className={mobileActiveView === 'dashboard' ? 'flex-1 overflow-hidden' : 'hidden'}>
                        <div className="fixed top-0 left-0 right-0 z-10 bg-background pt-[env(safe-area-inset-top)]">
                            <NavBar
                                user={user}
                                selectedTab={selectedTab}
                                onTabChange={handleTabChange}
                                isSidebarExpanded={true}
                            />
                        </div>
                        <main className="pt-[calc(3.5rem+env(safe-area-inset-top))] w-full h-full overflow-hidden flex flex-col">
                            <div className={`${selectedTab === 'flow' || selectedTab === 'settings' || selectedTab === 'debug' || selectedTab === 'dashboard' ? 'flex-1 min-h-0 min-w-0' : 'p-4 w-fit min-w-full'}`}>
                                {renderTabContent()}
                            </div>
                        </main>
                    </div>

                    {/* Mobile Bottom Tab Bar */}
                    <div className="flex-shrink-0 bg-card/80 backdrop-blur-sm border-t border-border pb-[env(safe-area-inset-bottom)]">
                        <div className="flex items-center justify-around h-14">
                            <button
                                onClick={() => setMobileActiveView('chat')}
                                className={cn(
                                    "flex flex-col items-center justify-center flex-1 h-full transition-colors",
                                    mobileActiveView === 'chat'
                                        ? "text-foreground"
                                        : "text-muted-foreground"
                                )}
                            >
                                <MessageCircle
                                    className="w-5 h-5 mb-0.5"
                                    fill={mobileActiveView === 'chat' ? "currentColor" : "none"}
                                    strokeWidth={mobileActiveView === 'chat' ? 0 : 2}
                                />
                                <span className="text-xs">Chat</span>
                            </button>
                            <button
                                onClick={() => setMobileActiveView('dashboard')}
                                className={cn(
                                    "flex flex-col items-center justify-center flex-1 h-full transition-colors",
                                    mobileActiveView === 'dashboard'
                                        ? "text-foreground"
                                        : "text-muted-foreground"
                                )}
                            >
                                <LayoutGrid
                                    className="w-5 h-5 mb-0.5"
                                    fill={mobileActiveView === 'dashboard' ? "currentColor" : "none"}
                                    strokeWidth={mobileActiveView === 'dashboard' ? 0 : 2}
                                />
                                <span className="text-xs">Dashboard</span>
                            </button>
                        </div>
                    </div>
                </div>
            ) : (
                // Desktop Layout
                <div className="min-h-screen flex">
                    <NoClick
                        isExpanded={isChatExpanded}
                        noAnimation={chatNoAnim}
                        onExpandChange={(expanded) => {
                            // Clicking the collapsed bar (or any non-"/" path)
                            // animates; "/" sets chatNoAnim before this runs.
                            if (expanded) setChatNoAnim(false);
                            setIsChatExpanded(expanded);
                        }}
                        onWidthChange={setChatWidth}
                        onDragChange={setIsDragging}
                        isMobileMode={false}
                        userEmail={user.email}
                        userAvatarUrl={user.avatar_url}
                    />
                    <div
                        className="fixed top-0 right-0 bottom-0 flex flex-col z-0 overflow-x-hidden"
                        style={{
                            left: isChatExpanded ? `${chatWidth}px` : '50px',
                            transition: isDragging || chatNoAnim
                                ? 'none'
                                : 'all 300ms ease-in-out',
                        }}
                    >
                        <div className="flex-shrink-0 relative z-10">
                            <NavBar
                                user={user}
                                selectedTab={selectedTab}
                                onTabChange={handleTabChange}
                                isSidebarExpanded={isChatExpanded}
                            />
                        </div>
                        <main className="flex-1 min-h-0 w-full overflow-hidden">
                            <div className={`${selectedTab === 'flow' || selectedTab === 'settings' || selectedTab === 'debug' || selectedTab === 'dashboard' ? 'h-full' : 'p-4 w-fit min-w-full'}`}>
                                {renderTabContent()}
                            </div>
                        </main>
                    </div>
                </div>
            )}
        </WorkflowBrowserDataProvider>
        </ChatDrawerProvider>
        </OnboardingProvider>
        </>
    );
}

export default function Dashboard(props: DashboardProps) {
    // Custom client-only rendering to avoid remix-utils React 18 dependency
    // This prevents useSyncExternalStore errors during SSR/hydration
    const [isClient, setIsClient] = useState(false);

    useEffect(() => {
        setIsClient(true);
    }, []);

    if (!isClient) {
        return <div>Loading...</div>;
    }

    return <DashboardContent {...props} />;
}
