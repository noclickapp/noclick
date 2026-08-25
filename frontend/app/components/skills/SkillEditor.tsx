/**
 * SkillEditor — inline tabbed editor for a single skill.
 * Renders in-place inside whatever container hosts it (Settings content area,
 * Debug panel, etc.) — no fixed positioning. The host is responsible for layout
 * height; the editor itself uses h-full and lays out its own back button +
 * tabs + content + footer save bar.
 */

import { useCallback, useEffect, useMemo, useState, lazy, Suspense } from 'react';
import { ArrowLeft, Brain, FileText, Workflow as WorkflowIcon, Trash2, Check, Loader2, ShieldCheck, Lock, Share2 } from 'lucide-react';
import { sendEventWithCallback } from '~/lib/socket-sender';
// Lazy so the skills settings tab (statically reachable from the dashboard via
// Settings) doesn't drag the workflow editor + node-component registry (~4.7MB)
// into the dashboard's initial bundle. Loads when the skill's workflow tab opens.
const FlowCanvas = lazy(() => import('~/components/workflow/FlowCanvas'));
import { ShareDialog } from '~/components/shared/popups/ShareDialog';
import { DeleteConfirmPopup } from '~/components/shared/popups/DeleteConfirmPopup';
import { canEditSkill, type SkillDetail, type SkillScope } from './skillTypes';

type Tab = 'content' | 'workflow';

type SaveState = 'idle' | 'saving' | 'saved' | 'error';

export function SkillEditor({
    skillId,
    scope,
    onClose,
    onChanged,
    onDeleted,
}: {
    skillId: string;
    scope: SkillScope;
    onClose: () => void;
    onChanged?: () => void;
    onDeleted?: () => void;
}) {
    const [detail, setDetail] = useState<SkillDetail | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [tab, setTab] = useState<Tab>('content');
    const [draft, setDraft] = useState({
        name: '',
        description: '',
        body_text: '',
        enabled: true,
    });
    const [saveState, setSaveState] = useState<SaveState>('idle');
    const [shareOpen, setShareOpen] = useState(false);
    const [deleteOpen, setDeleteOpen] = useState(false);

    // Initial load
    useEffect(() => {
        sendEventWithCallback(
            { event_name: 'skill:get', skill_id: skillId } as any,
            (resp: any) => {
                if (resp?.error) {
                    setError(resp.error);
                    return;
                }
                const s = resp.skill as SkillDetail;
                setDetail(s);
                setDraft({
                    name: s.name,
                    description: s.description ?? '',
                    body_text: s.body_text ?? '',
                    enabled: s.enabled,
                });
            },
        );
    }, [skillId]);

    const editable = useMemo(
        () => (detail ? canEditSkill(detail, scope) : false),
        [detail, scope],
    );

    const dirty = useMemo(() => {
        if (!detail) return false;
        return (
            draft.name !== detail.name ||
            draft.description !== (detail.description ?? '') ||
            draft.body_text !== (detail.body_text ?? '') ||
            draft.enabled !== detail.enabled
        );
    }, [draft, detail]);

    const save = useCallback(() => {
        if (!detail || !dirty || !editable) return;
        setSaveState('saving');
        sendEventWithCallback(
            {
                event_name: 'skill:update',
                skill_id: skillId,
                name: draft.name.trim() || detail.name,
                description: draft.description,
                body_text: draft.body_text,
                enabled: draft.enabled,
            } as any,
            (resp: any) => {
                if (resp?.error) {
                    setError(resp.error);
                    setSaveState('error');
                    return;
                }
                const updated = resp.skill as SkillDetail;
                setDetail(updated);
                setDraft({
                    name: updated.name,
                    description: updated.description ?? '',
                    body_text: updated.body_text ?? '',
                    enabled: updated.enabled,
                });
                setSaveState('saved');
                onChanged?.();
                // Briefly show "Saved" then go back to idle.
                setTimeout(() => setSaveState((s) => (s === 'saved' ? 'idle' : s)), 1500);
            },
        );
    }, [detail, dirty, editable, skillId, draft, onChanged]);

    const deleteSkill = useCallback(() => {
        if (!detail || !editable) return;
        sendEventWithCallback(
            { event_name: 'skill:delete', skill_id: skillId } as any,
            (resp: any) => {
                if (resp?.error) {
                    setError(resp.error);
                    return;
                }
                onDeleted?.();
                onClose();
            },
        );
    }, [detail, editable, skillId, onDeleted, onClose]);

    const headerName = detail?.name?.trim() ? detail.name : 'Untitled skill';

    return (
        <div className="h-full flex flex-col bg-background">
            {/* Header */}
            <div className="flex items-center justify-between gap-3 shrink-0 mb-3">
                <div className="flex items-center gap-3 min-w-0">
                    <button
                        onClick={onClose}
                        className="flex items-center justify-center w-8 h-8 text-muted-foreground/70 dark:text-white/40 hover:text-foreground/70 hover:bg-foreground/[0.05] rounded-full transition-colors shrink-0"
                        title="Back to skills"
                        aria-label="Back to skills"
                    >
                        <ArrowLeft className="h-4 w-4" />
                    </button>
                    <div className="h-8 w-8 rounded-lg bg-foreground/[0.05] border border-border dark:border-white/[0.08] flex items-center justify-center shrink-0">
                        <Brain className="h-4 w-4 text-muted-foreground dark:text-white/60" />
                    </div>
                    <div className="min-w-0">
                        <div className="flex items-center gap-2">
                            <h2 className="text-lg font-semibold text-foreground truncate">{detail ? headerName : 'Loading…'}</h2>
                            {detail?.is_system && <Pill tone="violet" icon={ShieldCheck}>System</Pill>}
                            {!editable && detail && <Pill tone="zinc" icon={Lock}>Read-only</Pill>}
                        </div>
                        <div className="text-[11px] text-muted-foreground/60 dark:text-white/30 font-mono truncate mt-0.5">{skillId}</div>
                    </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                    <SaveStatus state={saveState} dirty={dirty} editable={editable} />
                    {detail && !detail.is_system && scope !== 'shared' && (
                        <button
                            onClick={() => setShareOpen(true)}
                            className="inline-flex items-center gap-1.5 h-9 px-3 text-sm font-medium bg-card dark:bg-foreground/[0.05] border border-border dark:border-white/[0.08] hover:bg-muted dark:hover:bg-foreground/[0.08] hover:border-muted-foreground/30 dark:hover:border-white/[0.12] text-foreground/80 rounded-lg transition-colors"
                            title="Share this skill"
                        >
                            <Share2 className="h-3.5 w-3.5" />
                            Share
                        </button>
                    )}
                    {editable && (
                        <button
                            onClick={save}
                            disabled={!dirty || saveState === 'saving'}
                            className="inline-flex items-center gap-1.5 h-9 px-4 text-sm font-medium bg-primary text-primary-foreground rounded-lg hover:bg-foreground/90 disabled:opacity-40 transition-colors"
                            title="Save changes"
                        >
                            {saveState === 'saving' ? 'Saving…' : 'Save'}
                        </button>
                    )}
                </div>
            </div>

            {/* Tab bar — pill style, matches FlowCanvas / FlowHelperView HeaderTab */}
            <div className="flex items-center gap-1 shrink-0 mb-3">
                <TabButton active={tab === 'content'} onClick={() => setTab('content')} icon={FileText} label="Content" />
                <TabButton active={tab === 'workflow'} onClick={() => setTab('workflow')} icon={WorkflowIcon} label="Workflow" />
            </div>

            {error && (
                <div className="mb-4 px-3 py-2 text-xs text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/50 rounded-xl shrink-0">
                    {error}
                </div>
            )}

            {/* Body */}
            <div className="flex-1 min-h-0">
                {tab === 'content' && (
                    <ContentTab
                        draft={draft}
                        editable={editable}
                        onChange={setDraft}
                        onBlurSave={save}
                        onDelete={() => setDeleteOpen(true)}
                        canDelete={editable}
                    />
                )}
                {tab === 'workflow' && (
                    <div className="h-full rounded-xl border border-border dark:border-white/[0.06] overflow-hidden bg-background dark:bg-black/40">
                        <Suspense fallback={<div className="h-full w-full bg-sunken" />}>
                            <FlowCanvas
                                workflowId={skillId}
                                source={{ kind: 'skill', id: skillId }}
                                onBack={onClose}
                            />
                        </Suspense>
                    </div>
                )}
            </div>

            <ShareDialog
                isOpen={shareOpen}
                onOpenChange={setShareOpen}
                resource={detail ? { id: detail.id, name: detail.name } : null}
                resourceType="skill"
            />

            <DeleteConfirmPopup
                itemType="Skill"
                itemId={detail?.id}
                itemName={detail?.name}
                isOpen={deleteOpen}
                onOpenChange={setDeleteOpen}
                onConfirmDelete={deleteSkill}
            />
        </div>
    );
}

function ContentTab({
    draft,
    editable,
    onChange,
    onBlurSave,
    onDelete,
    canDelete,
}: {
    draft: { name: string; description: string; body_text: string; enabled: boolean };
    editable: boolean;
    onChange: (d: { name: string; description: string; body_text: string; enabled: boolean }) => void;
    onBlurSave: () => void;
    onDelete: () => void;
    canDelete: boolean;
}) {
    return (
        <div className="h-full overflow-auto scrollbar-subtle">
            <div className="max-w-3xl space-y-6 pb-6">
                    <Section title="Name">
                        <input
                            value={draft.name}
                            onChange={(e) => onChange({ ...draft, name: e.target.value })}
                            onBlur={onBlurSave}
                            disabled={!editable}
                            placeholder="e.g. Apple-style copy guidelines"
                            className="w-full h-9 px-3 text-sm bg-card dark:bg-foreground/[0.03] border border-border dark:border-white/[0.08] rounded-lg text-foreground placeholder-foreground/20 outline-none focus:border-foreground/20 disabled:opacity-60"
                        />
                    </Section>

                    <Section title="Description" hint="Few-sentence retrieval hint shown to the agent before it decides to load the body.">
                        <textarea
                            value={draft.description}
                            onChange={(e) => onChange({ ...draft, description: e.target.value })}
                            onBlur={onBlurSave}
                            disabled={!editable}
                            rows={3}
                            placeholder="When and why should the agent load this skill?"
                            className="w-full bg-card dark:bg-foreground/[0.03] border border-border dark:border-white/[0.08] focus:border-foreground/20 rounded-lg px-3 py-2 text-sm text-foreground placeholder-foreground/20 resize-y focus:outline-none disabled:opacity-60"
                        />
                    </Section>

                    <Section title="Text body" hint="Optional prose, instructions, examples, or background context.">
                        <textarea
                            value={draft.body_text}
                            onChange={(e) => onChange({ ...draft, body_text: e.target.value })}
                            onBlur={onBlurSave}
                            disabled={!editable}
                            rows={14}
                            placeholder="Markdown, code samples, references — anything the agent should remember."
                            className="w-full bg-card dark:bg-foreground/[0.03] border border-border dark:border-white/[0.08] focus:border-foreground/20 rounded-lg px-3 py-2 text-xs text-foreground placeholder-foreground/20 font-mono resize-y focus:outline-none disabled:opacity-60"
                        />
                    </Section>

                    <Section title="Status">
                        <div className="flex items-center justify-between bg-card dark:bg-foreground/[0.03] border border-border dark:border-white/[0.06] rounded-xl px-4 py-3">
                            <div>
                                <div className="text-sm text-foreground">Enabled</div>
                                <div className="text-[11px] text-muted-foreground/70 dark:text-white/40 mt-0.5">
                                    When off, this skill is excluded from builder calls.
                                </div>
                            </div>
                            <SwitchControl
                                enabled={draft.enabled}
                                disabled={!editable}
                                onClick={() => {
                                    if (!editable) return;
                                    onChange({ ...draft, enabled: !draft.enabled });
                                    requestAnimationFrame(onBlurSave);
                                }}
                            />
                        </div>
                    </Section>

                {canDelete && (
                    <Section title="Danger zone">
                        <button
                            onClick={onDelete}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-red-50 dark:bg-red-950/30 hover:bg-red-100 dark:hover:bg-red-950/50 text-red-700 dark:text-red-300 border border-red-200 dark:border-red-900/50 rounded-lg transition-colors"
                        >
                            <Trash2 className="h-3.5 w-3.5" />
                            Delete skill
                        </button>
                    </Section>
                )}
            </div>
        </div>
    );
}

function SwitchControl({
    enabled,
    disabled,
    onClick,
}: {
    enabled: boolean;
    disabled?: boolean;
    onClick: () => void;
}) {
    return (
        <button
            type="button"
            onClick={onClick}
            disabled={disabled}
            aria-pressed={enabled}
            className={`relative inline-flex shrink-0 h-5 w-9 rounded-full border transition-colors ${
                disabled ? 'cursor-not-allowed opacity-40' : 'cursor-pointer'
            } ${
                enabled
                    ? 'bg-foreground/80 border-primary/40'
                    : 'bg-foreground/[0.04] border-border dark:border-white/[0.10] hover:border-muted-foreground/40 dark:hover:border-white/[0.18]'
            }`}
        >
            <span
                className={`absolute top-0.5 h-3.5 w-3.5 rounded-full transition-transform ${
                    enabled ? 'bg-primary-foreground translate-x-[18px]' : 'bg-foreground/40 translate-x-0.5'
                }`}
            />
        </button>
    );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
    return (
        <div>
            <div className="mb-2">
                <div className="text-xs font-medium text-muted-foreground dark:text-white/60">{title}</div>
                {hint && <div className="text-[11px] text-muted-foreground/60 dark:text-white/30 mt-0.5">{hint}</div>}
            </div>
            {children}
        </div>
    );
}

// Pill-style tab matching the HeaderTab pattern in FlowCanvas / FlowHelperView.
function TabButton({
    active,
    onClick,
    icon: Icon,
    label,
}: {
    active: boolean;
    onClick: () => void;
    icon: React.ComponentType<{ className?: string }>;
    label: string;
}) {
    return (
        <button
            onClick={onClick}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                active ? 'bg-foreground/[0.08] text-foreground' : 'text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 hover:bg-foreground/[0.02]'
            }`}
        >
            <Icon className="h-3.5 w-3.5" />
            <span>{label}</span>
        </button>
    );
}

function SaveStatus({ state, dirty, editable }: { state: SaveState; dirty: boolean; editable: boolean }) {
    if (!editable) return null;
    if (state === 'saving') {
        return (
            <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground/70 dark:text-white/40">
                <Loader2 className="h-3 w-3 animate-spin" />
                Saving…
            </span>
        );
    }
    if (state === 'saved' && !dirty) {
        return (
            <span className="inline-flex items-center gap-1 text-[11px] text-emerald-600 dark:text-emerald-400">
                <Check className="h-3 w-3" />
                Saved
            </span>
        );
    }
    if (dirty) {
        return <span className="text-[11px] text-muted-foreground/70 dark:text-white/40">Unsaved</span>;
    }
    return null;
}

const pillTone: Record<string, string> = {
    violet: 'bg-violet-500/10 text-violet-700 dark:text-violet-300 border-violet-500/30',
    zinc: 'bg-foreground/[0.05] text-muted-foreground dark:text-white/50 border-border dark:border-white/[0.08]',
};

function Pill({
    children,
    tone,
    icon: Icon,
}: {
    children: React.ReactNode;
    tone: 'violet' | 'zinc';
    icon?: React.ComponentType<{ className?: string }>;
}) {
    return (
        <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md border text-[10px] font-medium uppercase tracking-wide ${pillTone[tone]}`}>
            {Icon && <Icon className="h-2.5 w-2.5" />}
            {children}
        </span>
    );
}
