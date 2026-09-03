// The Dashboard tab (replaces Feed): the Bento layout over live data from
// `dashboard:overview`, with the real action seam — approvals, builder answers
// and proposals go to their sockets, everything else navigates — and the
// drill-down section carried in `?focus=`. Credits come from the shared credit
// store the navbar chip already keeps warm.
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react';
import { useSearchParams } from 'react-router';
import { toast } from 'sonner';
import { BentoDashboard, type BentoConfig, type FullViewOverrides } from '~/components/dashboard/variants';
import { DashboardActionsContext, type DashboardActions } from '~/components/dashboard/primitives';
import type { DashboardData, FileEntry, FileSource, FocusId, RunRow } from '~/components/dashboard/types';
import { dismissAttention, fetchDashboardOverview, useDashboardOverview, type WorkspaceRef } from '~/hooks/useDashboardOverview';
import { useCreditUsage } from '~/hooks/useCreditUsage';
import { useValtioState } from '~/hooks/useValtioState';
import { uploadWorkspaceFiles } from '~/hooks/useAgentWorkspaceFiles';
import { useResourceUpload } from '~/hooks/useResourceUpload';
import { sendEventAsync } from '~/lib/socket-sender';
import { DASHBOARD_FOCUS_IDS, goToWorkflowNode, navigateToSettings, navigateToUsage, navigateToWorkflow } from '~/lib/navigation';
import { isLocalEdition } from '~/lib/edition';
import { openCreateCredential } from '~/components/shared/popups/CreateCredentialDialog';
import { DashboardSkeleton } from '~/components/dashboard/DashboardSkeleton';
import { FilePreviewDialog, type FilePreviewRequest } from '~/components/dashboard/FilePreviewDialog';
import { CredentialDeleteDialog, type DeletableCredential } from '~/components/credential/CredentialDeleteDialog';
import { Skeleton } from '~/components/ui/skeleton';

// Drill-downs that ARE a Settings page (credentials, usage) mount the Settings
// component itself, so the two never drift; the Story popup pulls the run
// renderer, which nobody pays for until a run is opened.
const CredentialsSettings = lazy(() => import('~/components/settings/CredentialsSettings').then((m) => ({ default: m.CredentialsSettings })));
const UsageDashboard = lazy(() => import('~/components/usage/UsageDashboard').then((m) => ({ default: m.UsageDashboard })));
const DashboardRunDialog = lazy(() => import('~/components/dashboard/DashboardRunDialog').then((m) => ({ default: m.DashboardRunDialog })));

function SettingsFallback() {
    return (
        <div className="space-y-3 py-2" aria-busy="true">
            {[72, 56, 64, 48].map((w, i) => (
                <Skeleton key={i} className="h-10 rounded-lg" style={{ width: `${w}%` }} />
            ))}
        </div>
    );
}
const CredentialsFocus = () => (
    <Suspense fallback={<SettingsFallback />}>
        <CredentialsSettings embedded hideTitle />
    </Suspense>
);
const UsageFocus = () => (
    <Suspense fallback={<SettingsFallback />}>
        <UsageDashboard embedded />
    </Suspense>
);
const FULL_VIEW_OVERRIDES: FullViewOverrides = { credentials: CredentialsFocus, credits: UsageFocus };

/** The shipped look: hairline cards, eyebrow headers, the ledger stat strip. */
const PRODUCT_CONFIG: BentoConfig = { surface: 'hairline', header: 'eyebrow', kpi: 'ledger', layout: 'balanced' };

const WORKSPACE_LISTINGS = 8;

type Wire = Record<string, unknown>;
type Envelope = { error?: string; data?: Wire } & Wire;

/** Send one request/response event by name. Several of these (builder answers,
 *  decisions) have no generated request model, so the name is passed through. */
async function call(event: string, payload: Wire, timeoutMs = 30000): Promise<Wire> {
    const request = { event_name: event, ...payload } as unknown as Parameters<typeof sendEventAsync>[0];
    const response = (await sendEventAsync(request, undefined, timeoutMs)) as Envelope | null;
    if (response?.error) throw new Error(response.error);
    return (response?.data ?? response ?? {}) as Wire;
}

function fileKindFromPath(path: string): FileEntry['kind'] {
    const ext = path.includes('.') ? path.slice(path.lastIndexOf('.') + 1).toLowerCase() : '';
    if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'].includes(ext)) return 'image';
    if (['mp4', 'webm', 'mov', 'm4v', 'mkv'].includes(ext)) return 'video';
    if (['mp3', 'wav', 'ogg', 'oga', 'm4a', 'aac'].includes(ext)) return 'audio';
    if (['csv', 'tsv', 'xlsx', 'json', 'parquet'].includes(ext)) return 'data';
    if (['py', 'js', 'ts', 'tsx', 'sh', 'sql', 'yaml', 'yml', 'toml'].includes(ext)) return 'code';
    if (['zip', 'tar', 'gz', '7z'].includes(ext)) return 'archive';
    if (['md', 'txt', 'pdf', 'doc', 'docx', 'log'].includes(ext)) return 'doc';
    return 'other';
}

function mtimeIso(raw: unknown): string {
    if (typeof raw === 'number') return new Date(raw > 1e12 ? raw : raw * 1000).toISOString();
    if (typeof raw === 'string' && raw) return raw;
    return new Date(0).toISOString();
}

/** One agent workspace volume as a Files place — the same listing the chat's
 *  Files panel shows, with the upload capability editors receive. */
async function listWorkspace(w: WorkspaceRef): Promise<FileSource | null> {
    try {
        const d = await call('agent_workspace:list', { workflow_id: w.workflow.id, node_id: w.agent.nodeId, conversation_key: w.conversationKey }, 20000);
        if (!d?.success) return null;
        const mount = (typeof d.workspace === 'string' && d.workspace) || '/workspace';
        const uploadUrlPath = typeof d.upload_url_path === 'string' ? d.upload_url_path : undefined;
        return {
            id: w.id,
            kind: 'workspace',
            label: `${w.agent.label} · ${w.conversationTitle || w.conversationKey}`,
            sublabel: `Agent workspace · mounted at ${mount}`,
            workflow: w.workflow,
            agent: w.agent,
            conversationTitle: w.conversationTitle,
            conversationKey: w.conversationKey,
            mount,
            uploadUrlPath,
            writable: !!uploadUrlPath,
            files: ((d.files as Array<Record<string, unknown>>) ?? []).map((f) => ({
                path: String(f.path ?? ''),
                size: Number(f.size ?? 0),
                mtime: mtimeIso(f.mtime),
                kind: fileKindFromPath(String(f.path ?? '')),
                urlPath: typeof f.url_path === 'string' ? f.url_path : undefined,
            })),
            truncated: Boolean(d.truncated),
        };
    } catch {
        return null;
    }
}

/** Agent /workspace volumes are listed lazily — one volume call each — only
 *  while the Files drill-down is open, for the most recent conversations.
 *  `reload` re-lists one place after an upload or delete. */
function useWorkspaceSources(workspaces: WorkspaceRef[] | undefined, enabled: boolean, stamp: string | undefined): { sources: FileSource[]; reload: (id: string) => Promise<void> } {
    const [sources, setSources] = useState<FileSource[]>([]);
    useEffect(() => {
        if (!enabled || !workspaces?.length) return;
        let cancelled = false;
        (async () => {
            const listed = await Promise.all(workspaces.slice(0, WORKSPACE_LISTINGS).map(listWorkspace));
            if (!cancelled) setSources(listed.filter((s): s is FileSource => s !== null));
        })();
        return () => {
            cancelled = true;
        };
    }, [enabled, workspaces, stamp]);
    const reload = useCallback(
        async (id: string) => {
            const w = workspaces?.find((x) => x.id === id);
            const next = w ? await listWorkspace(w) : null;
            if (next) setSources((prev) => prev.map((s) => (s.id === id ? next : s)));
        },
        [workspaces]
    );
    return { sources, reload };
}

export function DashboardTab() {
    const { overview, loading, error, dismissed } = useDashboardOverview();
    const credit = useCreditUsage();
    const [params, setParams] = useSearchParams();
    const [, setPendingCreditAction] = useValtioState<'credit-exhausted' | 'user-initiated' | null>('global', 'pending_credit_action', null);

    const focusParam = params.get('focus');
    const focus = (DASHBOARD_FOCUS_IDS as readonly string[]).includes(focusParam ?? '') ? (focusParam as FocusId) : null;
    // The drill-down survives a trip to another tab: the tab switch strips
    // `?focus=` from the URL, so the last drill-down is kept for the session and
    // re-applied when the tab mounts again. Leaving it on purpose — the back
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
        if (!focus && lastFocus) onFocus(lastFocus);
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

    const { sources: workspaceSources, reload: reloadWorkspace } = useWorkspaceSources(overview?.workspaces, focus === 'files', overview?.generatedAt);
    const [preview, setPreview] = useState<FilePreviewRequest | null>(null);
    const [openRun, setOpenRun] = useState<RunRow | null>(null);
    const [credentialToDelete, setCredentialToDelete] = useState<DeletableCredential | null>(null);
    const { uploadFile } = useResourceUpload();
    const fileInput = useRef<HTMLInputElement>(null);
    const uploadTarget = useRef<FileSource | null>(null);

    const sectionErrors = overview?.errors;
    useEffect(() => {
        const failed = Object.keys(sectionErrors ?? {});
        if (failed.length) toast.error(`Some dashboard sections did not load: ${failed.join(', ')}`);
    }, [sectionErrors]);

    // Top-ups, tiers and the reset date are hosted billing; the open edition's
    // credit hook (an override) has none of them, so they are read as optional.
    const hostedCredit: Pick<typeof credit, 'used'> & Partial<{ nextRefreshAt: string | null; topup_credits: number; effectiveTier: string | null }> = credit;
    const data: DashboardData | null = useMemo(() => {
        if (!overview) return null;
        const cap = credit.limit ?? credit.monthlyCap ?? 0;
        return {
            workspace: overview.workspace,
            now,
            attention: overview.attention,
            runs: overview.runs,
            agents: overview.agents,
            files: [...overview.files, ...workspaceSources],
            credentials: overview.credentials,
            triggers: overview.triggers,
            upcoming: overview.upcoming,
            credits: {
                used: credit.used,
                cap,
                period: credit.period ?? 'month',
                nextRefreshAt: hostedCredit.nextRefreshAt ?? '',
                topup: hostedCredit.topup_credits ?? 0,
                tier: hostedCredit.effectiveTier ?? '',
                spendByDay: [],
                topSpenders: [],
            },
            notifications: overview.notifications,
        };
    }, [overview, workspaceSources, now, credit.used, credit.limit, credit.monthlyCap, credit.period, hostedCredit.nextRefreshAt, hostedCredit.topup_credits, hostedCredit.effectiveTier]);

    const refresh = useCallback(() => fetchDashboardOverview(), []);
    const failing = useCallback(
        (what: string) => (e: unknown) => {
            toast.error(`${what} failed: ${e instanceof Error ? e.message : String(e)}`);
            void refresh();
        },
        [refresh]
    );

    // Upload into the place the user picked: workspace volumes take the signed
    // upload path the listing minted, workflow resources go through the same
    // create → presigned PUT flow the interface blocks use.
    const onFilesPicked = useCallback(
        async (e: ChangeEvent<HTMLInputElement>) => {
            const files = Array.from(e.target.files ?? []);
            e.target.value = '';
            const source = uploadTarget.current;
            if (!source || !files.length) return;
            const id = toast.loading(`Uploading ${files.length === 1 ? files[0].name : `${files.length} files`}…`);
            try {
                if (source.kind === 'workspace') {
                    if (!source.uploadUrlPath) throw new Error('You can only view this workspace');
                    await uploadWorkspaceFiles(source.uploadUrlPath, files, (p) => toast.loading(`Uploading ${p.fileName} · ${Math.round(p.fraction * 100)}%`, { id }));
                    await reloadWorkspace(source.id);
                } else if (source.kind === 'resources' && source.workflow) {
                    for (const f of files) await uploadFile(f, source.workflow.id, null);
                    await refresh();
                } else {
                    throw new Error('This place is read-only here');
                }
                toast.success(`Uploaded to ${source.label}`, { id });
            } catch (err) {
                toast.error(`Upload failed: ${err instanceof Error ? err.message : String(err)}`, { id });
            }
        },
        [reloadWorkspace, refresh, uploadFile]
    );

    const actions = useMemo<DashboardActions>(
        () => ({
            dismissed: new Set(dismissed),
            openWorkflow: (wf, nodeId) => (nodeId ? goToWorkflowNode(wf.id, nodeId) : navigateToWorkflow({ id: wf.id, name: wf.name })),
            respondApproval: (item, decision, values) => {
                dismissAttention(item.id);
                call('approval:respond', { approval_id: item.meta?.approvalId, decision, values }).then(refresh).catch(failing('Approval'));
            },
            answerAsk: (item, answers) => {
                dismissAttention(item.id);
                call('workflow:builder:input_response', { conversation_id: item.meta?.conversationId, ask_id: item.meta?.askId, values: answers, dismissed: false })
                    .then(refresh)
                    .catch(failing('Answer'));
            },
            dismissAsk: (item) => {
                dismissAttention(item.id);
                call('workflow:builder:input_response', { conversation_id: item.meta?.conversationId, ask_id: item.meta?.askId, values: {}, dismissed: true })
                    .then(refresh)
                    .catch(failing('Skip'));
            },
            shareAsk: async (item) => {
                try {
                    const d = await call('workflow:builder:share_ask', { conversation_id: item.meta?.conversationId, ask_id: item.meta?.askId });
                    const url = typeof d.url === 'string' ? d.url : typeof d.link_url === 'string' ? d.link_url : null;
                    if (!url) throw new Error('No link returned');
                    return url;
                } catch (e) {
                    toast.error(`Could not mint a link: ${e instanceof Error ? e.message : String(e)}`);
                    return null;
                }
            },
            decideProposal: (item, decision) => {
                dismissAttention(item.id);
                call('agent:builder_decision', {
                    workflow_id: item.workflow.id,
                    node_id: item.meta?.nodeId ?? null,
                    conversation_id: item.meta?.conversationId,
                    proposal_id: item.meta?.proposalId,
                    decision,
                })
                    .then(refresh)
                    .catch(failing('Decision'));
                if (decision === 'approved') {
                    // Same hand-off as the chat card: open the workflow, expand the
                    // builder, and submit the agent-anchored prompt.
                    navigateToWorkflow({ id: item.workflow.id, name: item.workflow.name });
                    const prompt = String(item.meta?.anchoredPrompt ?? item.title);
                    setTimeout(() => {
                        document.dispatchEvent(new CustomEvent('noclick:sidebar:expand'));
                        document.dispatchEvent(new CustomEvent('noclick:builder:submit', { detail: { prompt } }));
                    }, 400);
                }
            },
            copyLink: (item) => {
                const url = item.link ? new URL(item.link, window.location.origin).toString() : '';
                if (!url) return;
                navigator.clipboard?.writeText(url).then(() => toast.success('Link copied')).catch(() => toast.error('Could not copy'));
            },
            openLink: (item) => {
                if (item.link) window.open(new URL(item.link, window.location.origin).toString(), '_blank', 'noopener');
            },
            cancelCredentialRequest: (item) => {
                dismissAttention(item.id);
                call('credential:request:cancel', { credential_request_id: item.meta?.requestId }).then(refresh).catch(failing('Cancel'));
            },
            reconnectCredential: ({ credentialId, credentialType }) => openCreateCredential({ credentialType, credentialId }),
            openRun: (run) => navigateToWorkflow({ id: run.workflow.id, name: run.workflow.name }),
            openExecution: (run) => setOpenRun(run),
            openConversation: (turn) => goToWorkflowNode(turn.workflow.id, turn.agent.nodeId),
            openFile: (file, source) => setPreview({ file, source }),
            uploadTo: (source) => {
                uploadTarget.current = source;
                fileInput.current?.click();
            },
            deleteFile: async (file, source) => {
                try {
                    if (source.kind === 'workspace' && source.workflow && source.agent) {
                        await call('agent_workspace:delete', { workflow_id: source.workflow.id, node_id: source.agent.nodeId, conversation_key: source.conversationKey ?? null, path: file.path });
                        await reloadWorkspace(source.id);
                    } else if (source.kind === 'resources' && file.resourceId) {
                        await call('resource:delete', { resource_id: file.resourceId });
                        await refresh();
                    } else {
                        throw new Error('This place is read-only here');
                    }
                } catch (e) {
                    toast.error(`Delete failed: ${e instanceof Error ? e.message : String(e)}`);
                }
            },
            manageCredential: (c) => openCreateCredential({ credentialType: c.credentialType, credentialId: c.id }),
            openCredentialsSettings: () => navigateToSettings({ section: 'credentials' }),
            deleteCredential: (c) => setCredentialToDelete({ id: c.id, name: c.name }),
            connectAccount: () => openCreateCredential(),
            topUp: isLocalEdition() ? undefined : () => setPendingCreditAction('user-initiated'),
            openUsage: () => navigateToUsage(),
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
        }),
        [dismissed, refresh, failing, setPendingCreditAction, reloadWorkspace]
    );

    if (!data) {
        if (error && !loading) {
            return (
                <div className="flex h-full items-center justify-center" data-testid="dashboard-tab-error">
                    <div className="text-center">
                        <p className="m-0 text-[13px] text-foreground/75 dark:text-foreground/60">The dashboard could not load.</p>
                        <p className="m-0 mt-1 text-[11.5px] text-foreground/55 dark:text-foreground/35">{error}</p>
                        <button type="button" onClick={() => void refresh()} className="mt-3 rounded-md bg-primary px-3 py-1.5 text-[12px] font-medium text-primary-foreground">
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
                <BentoDashboard data={data} config={PRODUCT_CONFIG} focus={focus} onFocus={onFocus} fullViewOverrides={FULL_VIEW_OVERRIDES} />
            </div>
            <input ref={fileInput} type="file" multiple className="hidden" onChange={onFilesPicked} data-testid="dashboard-upload-input" />
            <FilePreviewDialog request={preview} onClose={() => setPreview(null)} onOpenWorkflow={(source) => source.workflow && actions.openWorkflow(source.workflow, source.agent?.nodeId)} />
            <CredentialDeleteDialog credential={credentialToDelete} onClose={() => setCredentialToDelete(null)} onDeleted={() => void refresh()} />
            {openRun && (
                <Suspense fallback={null}>
                    <DashboardRunDialog run={openRun} onClose={() => setOpenRun(null)} />
                </Suspense>
            )}
        </DashboardActionsContext.Provider>
    );
}
