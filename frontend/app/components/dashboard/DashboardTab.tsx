// The Activity page (the open edition's Dashboard tab): the Bento layout over
// live data from `dashboard:overview`, with the real action seam — approvals,
// builder answers and proposals go to their sockets, everything else navigates —
// and the drill-down section carried in `?focus=`.
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router';
import { toast } from 'sonner';
import { BentoDashboard, type BentoConfig } from '~/components/dashboard/variants';
import { DashboardActionsContext, type DashboardActions } from '~/components/dashboard/primitives';
import type { DashboardData, FocusId, RunRow } from '~/components/dashboard/types';
import { fetchDashboardOverview, useDashboardOverview } from '~/hooks/useDashboardOverview';
import { useAttentionActions } from '~/hooks/useAttentionActions';
import { useValtioState } from '~/hooks/useValtioState';
import { socketCall as call } from '~/lib/socketCall';
import { DASHBOARD_FOCUS_IDS, goToWorkflowNode, navigateToSettings, navigateToTab, navigateToUsage, navigateToWorkflow } from '~/lib/navigation';
import { askNoClick } from '~/lib/askNoClick';
import { isLocalEdition } from '~/lib/edition';
import { DashboardSkeleton } from '~/components/dashboard/DashboardSkeleton';

// The Story popup pulls the run renderer, which nobody pays for until a run is opened.
const DashboardRunDialog = lazy(() => import('~/components/dashboard/DashboardRunDialog').then((m) => ({ default: m.DashboardRunDialog })));

/** The shipped look: hairline cards, eyebrow headers, the ledger stat strip. */
const PRODUCT_CONFIG: BentoConfig = { surface: 'hairline', header: 'title', kpi: 'strip', layout: 'balanced' };

export function DashboardTab() {
    const { overview, loading, error, dismissed } = useDashboardOverview();
    const [params, setParams] = useSearchParams();
    const [, setPendingCreditAction] = useValtioState<'credit-exhausted' | 'user-initiated' | null>('global', 'pending_credit_action', null);

    const focusParam = params.get('focus');
    const focus = (DASHBOARD_FOCUS_IDS as readonly string[]).includes(focusParam ?? '') ? (focusParam as FocusId) : null;
    // The drill-down survives a trip to another page: the page switch strips
    // `?focus=` from the URL, so the last drill-down is kept for the session and
    // re-applied when the page mounts again. Leaving it on purpose — the back
    // button, Esc, or the browser's Back — forgets it.
    const [lastFocus, setLastFocus] = useValtioState<FocusId | null>('dashboard', 'last_focus', null);
    const onFocus = useCallback(
        (id: FocusId | null) => {
            setLastFocus(id);
            setParams(
                (prev) => {
                    const next = new URLSearchParams(prev);
                    if (id) next.set('focus', id);
                    else next.delete('focus');
                    return next;
                },
                { replace: !id }
            );
        },
        [setParams, setLastFocus]
    );
    const restored = useRef(false);
    useEffect(() => {
        if (restored.current) return;
        restored.current = true;
        if (!focus && lastFocus && (DASHBOARD_FOCUS_IDS as readonly string[]).includes(lastFocus)) onFocus(lastFocus);
        // eslint-disable-next-line react-hooks/exhaustive-deps -- mount only
    }, []);
    useEffect(() => {
        const onPop = () => {
            if (!new URLSearchParams(window.location.search).get('focus')) setLastFocus(null);
        };
        window.addEventListener('popstate', onPop);
        return () => window.removeEventListener('popstate', onPop);
    }, [setLastFocus]);

    // Relative times tick without a refetch.
    const [now, setNow] = useState(() => new Date().toISOString());
    useEffect(() => {
        const t = setInterval(() => setNow(new Date().toISOString()), 60_000);
        return () => clearInterval(t);
    }, []);

    const [openRun, setOpenRun] = useState<RunRow | null>(null);

    const sectionErrors = overview?.errors;
    useEffect(() => {
        const failed = Object.keys(sectionErrors ?? {});
        if (failed.length) toast.error(`Some activity did not load: ${failed.join(', ')}`);
    }, [sectionErrors]);

    const data: DashboardData | null = useMemo(() => {
        if (!overview) return null;
        return {
            workspace: overview.workspace,
            now,
            attention: overview.attention,
            runs: overview.runs,
            agents: overview.agents,
            triggers: overview.triggers,
            upcoming: overview.upcoming,
            notifications: overview.notifications,
        };
    }, [overview, now]);

    const refresh = useCallback(() => fetchDashboardOverview(), []);
    const failing = useCallback(
        (what: string) => (e: unknown) => {
            toast.error(`${what} failed: ${e instanceof Error ? e.message : String(e)}`);
            void refresh();
        },
        [refresh]
    );
    const attentionActions = useAttentionActions(refresh);

    const actions = useMemo<DashboardActions>(
        () => ({
            dismissed: new Set(dismissed),
            ...attentionActions,
            openRun: (run) => navigateToWorkflow({ id: run.workflow.id, name: run.workflow.name }),
            openExecution: (run) => setOpenRun(run),
            openConversation: (turn) => goToWorkflowNode(turn.workflow.id, turn.agent.nodeId),
            markNotificationsRead: (ids) => {
                call('dashboard:notifications:read', { ids: ids ?? null }).then(refresh).catch(failing('Mark read'));
            },
            openNotification: (n) => {
                if (!n.readAt) call('dashboard:notifications:read', { ids: [n.id] }).then(refresh).catch(() => {});
                if (n.category === 'credits') {
                    if (!isLocalEdition()) setPendingCreditAction('user-initiated');
                    else navigateToUsage();
                } else if (n.workflow?.id) {
                    navigateToWorkflow({ id: n.workflow.id, name: n.workflow.name });
                } else if (n.category === 'credential_revoked' || n.category === 'channel_disconnected') {
                    navigateToSettings({ section: 'credentials' });
                }
            },
            openPreferences: () => navigateToSettings({ section: 'notifications' }),
            // The app shell builds from its chat; the open edition's tabs build on the canvas.
            startAutomation: () => (isLocalEdition() ? navigateToTab('flow') : askNoClick('Build me an automation that ')),
        }),
        [dismissed, attentionActions, refresh, failing, setPendingCreditAction]
    );

    if (!data) {
        if (error && !loading) {
            return (
                <div className="flex h-full items-center justify-center" data-testid="dashboard-tab-error">
                    <div className="text-center">
                        <p className="m-0 text-[14px] text-foreground/80">Activity could not load.</p>
                        <p className="m-0 mt-1 text-[12.5px] text-muted-foreground">{error}</p>
                        <button type="button" onClick={() => void refresh()} className="mt-4 rounded-full bg-primary px-4 py-1.5 text-[13px] font-medium text-primary-foreground transition-opacity hover:opacity-90">
                            Try again
                        </button>
                    </div>
                </div>
            );
        }
        return <DashboardSkeleton />;
    }

    return (
        <DashboardActionsContext.Provider value={actions}>
            <div className="h-full" data-testid="dashboard-tab">
                <BentoDashboard data={data} config={PRODUCT_CONFIG} focus={focus} onFocus={onFocus} />
            </div>
            {openRun && (
                <Suspense fallback={null}>
                    <DashboardRunDialog run={openRun} onClose={() => setOpenRun(null)} />
                </Suspense>
            )}
        </DashboardActionsContext.Provider>
    );
}
