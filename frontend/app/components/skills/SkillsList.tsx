/**
 * SkillsList — top-level UI for browsing and managing skills (debug surface).
 * Reusable: drop it into any container and it owns fetching, sectioning
 * (Owned / Shared / System), inline expansion, the SkillEditor swap, the
 * create dialog, and the share dialog. Visual style mirrors the Settings
 * palette (white/[0.0X] over black) so debug feels native.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Brain, Plus, RefreshCw, X } from 'lucide-react';
import { sendEventWithCallback } from '~/lib/socket-sender';
import { ShareDialog } from '~/components/shared/popups/ShareDialog';
import { DeleteConfirmPopup } from '~/components/shared/popups/DeleteConfirmPopup';
import { SkillRow } from './SkillRow';
import { SkillRowExpansion } from './SkillRowExpansion';
import { SkillEditor } from './SkillEditor';
import type { SkillListResponse, SkillScope, SkillSummary } from './skillTypes';

type EditorState = { skillId: string; scope: SkillScope } | null;
type ShareState = { skill: SkillSummary } | null;
type DeleteState = { skill: SkillSummary } | null;

export function SkillsList() {
    const [owned, setOwned] = useState<SkillSummary[]>([]);
    const [shared, setShared] = useState<SkillSummary[]>([]);
    const [system, setSystem] = useState<SkillSummary[] | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [expanded, setExpanded] = useState<Set<string>>(new Set());
    const [editor, setEditor] = useState<EditorState>(null);
    const [createOpen, setCreateOpen] = useState(false);
    const [share, setShare] = useState<ShareState>(null);
    const [pendingDelete, setPendingDelete] = useState<DeleteState>(null);

    const isInternal = system !== null;

    const fetchList = useCallback(() => {
        setLoading(true);
        setError(null);
        sendEventWithCallback(
            { event_name: 'skill:list' } as any,
            (resp: SkillListResponse & { error?: string }) => {
                setLoading(false);
                if (resp?.error) {
                    setError(resp.error);
                    return;
                }
                setOwned(resp.owned || []);
                setShared(resp.shared || []);
                setSystem(resp.system ?? null);
            },
        );
    }, []);

    useEffect(() => {
        fetchList();
    }, [fetchList]);

    const toggleExpand = useCallback((id: string) => {
        setExpanded((prev) => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    }, []);

    // The single row toggle = "is this skill active for me right now?".
    // For owned/system skills that's the owner-side `enabled` flag.
    // For shared skills it's the inverse of the per-user mute (since the
    // viewer can't change `enabled`).
    const toggleActive = useCallback(
        (skill: SkillSummary, scope: SkillScope) => {
            if (scope === 'shared') {
                const currentlyActive = !skill.muted;
                sendEventWithCallback(
                    { event_name: 'skill:mute', skill_id: skill.id, muted: currentlyActive } as any,
                    (resp: any) => {
                        if (resp?.error) {
                            setError(resp.error);
                            return;
                        }
                        fetchList();
                    },
                );
                return;
            }
            sendEventWithCallback(
                { event_name: 'skill:update', skill_id: skill.id, enabled: !skill.enabled } as any,
                (resp: any) => {
                    if (resp?.error) {
                        setError(resp.error);
                        return;
                    }
                    fetchList();
                },
            );
        },
        [fetchList],
    );

    const confirmDelete = useCallback(
        (skill: SkillSummary) => {
            sendEventWithCallback(
                { event_name: 'skill:delete', skill_id: skill.id } as any,
                (resp: any) => {
                    if (resp?.error) {
                        setError(resp.error);
                        return;
                    }
                    fetchList();
                },
            );
        },
        [fetchList],
    );

    const stats = useMemo(() => {
        const total = owned.length + shared.length + (system?.length ?? 0);
        const active = [...owned, ...(system ?? [])].filter((s) => s.enabled).length
            + shared.filter((s) => !s.muted).length;
        const withWorkflow = [...owned, ...shared, ...(system ?? [])].filter((s) => s.has_workflow).length;
        return { total, active, withWorkflow };
    }, [owned, shared, system]);

    if (editor) {
        // No outer padding so the workflow canvas gets the full debug pane
        // height. SkillEditor manages its own internal spacing.
        return (
            <div className="h-full min-h-0 flex flex-col bg-background text-foreground px-4 pt-3">
                <SkillEditor
                    skillId={editor.skillId}
                    scope={editor.scope}
                    onClose={() => {
                        setEditor(null);
                        fetchList();
                    }}
                    onChanged={fetchList}
                    onDeleted={fetchList}
                />
            </div>
        );
    }

    return (
        <div className="h-full min-h-0 flex flex-col bg-background text-foreground">
            {/* Toolbar */}
            <div className="border-b border-border dark:border-white/[0.06] px-4 py-3 shrink-0">
                <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-3">
                        <div className="h-8 w-8 rounded-lg bg-foreground/[0.05] border border-border dark:border-white/[0.08] flex items-center justify-center">
                            <Brain className="h-4 w-4 text-muted-foreground dark:text-white/60" />
                        </div>
                        <div>
                            <div className="text-sm font-semibold text-foreground">Skills</div>
                            <div className="text-[11px] text-muted-foreground/70 dark:text-white/40">
                                Reusable agent context — description + optional text + optional workflow
                            </div>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        <Stat label="Active" value={stats.active} />
                        <Stat label="Workflows" value={stats.withWorkflow} />
                        <Stat label="Total" value={stats.total} />
                        <button
                            onClick={fetchList}
                            disabled={loading}
                            className="p-2 rounded-lg text-muted-foreground/70 dark:text-white/30 hover:text-foreground/80 hover:bg-foreground/[0.05] disabled:opacity-50 transition-colors"
                            title="Refresh"
                        >
                            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
                        </button>
                        <button
                            onClick={() => setCreateOpen(true)}
                            className="inline-flex items-center gap-1.5 h-9 px-3 text-sm font-medium bg-primary text-primary-foreground rounded-lg hover:bg-foreground/90 transition-colors"
                        >
                            <Plus className="h-4 w-4" />
                            New skill
                        </button>
                    </div>
                </div>
            </div>

            {/* Body */}
            <div className="flex-1 min-h-0 overflow-y-auto scrollbar-subtle">
                {error && (
                    <div className="m-4 px-3 py-2 text-xs text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/50 rounded-xl flex items-center justify-between">
                        <span>{error}</span>
                        <button onClick={() => setError(null)} className="text-muted-foreground/70 dark:text-white/40 hover:text-foreground/80">
                            <X className="h-3 w-3" />
                        </button>
                    </div>
                )}
                <div className="p-4 space-y-6">
                    {loading && stats.total === 0 ? (
                        <Empty title="Loading skills…" />
                    ) : stats.total === 0 ? (
                        <Empty
                            title="No skills yet"
                            description="Create your first skill to give the agent persistent context."
                            action={{ label: 'New skill', onClick: () => setCreateOpen(true) }}
                        />
                    ) : (
                        <>
                            <Section
                                title="Owned"
                                description="Skills you authored, including those scoped to your active workspace."
                                skills={owned}
                                scope="owned"
                                expanded={expanded}
                                onToggleExpand={toggleExpand}
                                onOpenEditor={(s) => setEditor({ skillId: s.id, scope: 'owned' })}
                                onToggleActive={(s) => toggleActive(s, 'owned')}
                                onShare={(s) => setShare({ skill: s })}
                                onDelete={(s) => setPendingDelete({ skill: s })}
                            />
                            {shared.length > 0 && (
                                <Section
                                    title="Shared with me"
                                    description="Skills shared via resource sharing — view-only by default."
                                    skills={shared}
                                    scope="shared"
                                    expanded={expanded}
                                    onToggleExpand={toggleExpand}
                                    onOpenEditor={(s) => setEditor({ skillId: s.id, scope: 'shared' })}
                                    onToggleActive={(s) => toggleActive(s, 'shared')}
                                    onShare={(s) => setShare({ skill: s })}
                                    onDelete={(s) => setPendingDelete({ skill: s })}
                                />
                            )}
                            {system && system.length > 0 && (
                                <Section
                                    title="System"
                                    description="Platform-maintained skills loaded into every internal builder call."
                                    skills={system}
                                    scope="system"
                                    expanded={expanded}
                                    onToggleExpand={toggleExpand}
                                    onOpenEditor={(s) => setEditor({ skillId: s.id, scope: 'system' })}
                                    onToggleActive={(s) => toggleActive(s, 'system')}
                                    onShare={(s) => setShare({ skill: s })}
                                    onDelete={(s) => setPendingDelete({ skill: s })}
                                />
                            )}
                        </>
                    )}
                </div>
            </div>

            {createOpen && (
                <CreateSkillDialog
                    isInternal={isInternal}
                    onCancel={() => setCreateOpen(false)}
                    onCreated={(newSkillId) => {
                        setCreateOpen(false);
                        fetchList();
                        setEditor({ skillId: newSkillId, scope: 'owned' });
                    }}
                />
            )}

            <ShareDialog
                isOpen={!!share}
                onOpenChange={(open) => {
                    if (!open) setShare(null);
                }}
                resource={share ? { id: share.skill.id, name: share.skill.name } : null}
                resourceType="skill"
            />

            <DeleteConfirmPopup
                itemType="Skill"
                itemId={pendingDelete?.skill.id}
                itemName={pendingDelete?.skill.name}
                isOpen={!!pendingDelete}
                onOpenChange={(open) => {
                    if (!open) setPendingDelete(null);
                }}
                onConfirmDelete={() => {
                    if (pendingDelete) confirmDelete(pendingDelete.skill);
                }}
            />
        </div>
    );
}

function Section({
    title,
    description,
    skills,
    scope,
    expanded,
    onToggleExpand,
    onOpenEditor,
    onToggleActive,
    onShare,
    onDelete,
}: {
    title: string;
    description?: string;
    skills: SkillSummary[];
    scope: SkillScope;
    expanded: Set<string>;
    onToggleExpand: (id: string) => void;
    onOpenEditor: (skill: SkillSummary) => void;
    onToggleActive: (skill: SkillSummary) => void;
    onShare: (skill: SkillSummary) => void;
    onDelete: (skill: SkillSummary) => void;
}) {
    if (skills.length === 0) return null;
    return (
        <section>
            <div className="mb-2 flex items-baseline justify-between">
                <div>
                    <h3 className="text-xs font-semibold text-muted-foreground dark:text-white/60 uppercase tracking-wide">{title}</h3>
                    {description && <p className="text-[11px] text-muted-foreground/60 dark:text-white/30 mt-0.5">{description}</p>}
                </div>
                <span className="text-[11px] text-muted-foreground/60 dark:text-white/30">{skills.length}</span>
            </div>
            <div className="space-y-2">
                {skills.map((skill) => {
                    const isExpanded = expanded.has(skill.id);
                    return (
                        <div key={skill.id}>
                            <SkillRow
                                skill={skill}
                                scope={scope}
                                isExpanded={isExpanded}
                                onOpenEditor={() => onOpenEditor(skill)}
                                onToggleExpand={() => onToggleExpand(skill.id)}
                                onToggleActive={() => onToggleActive(skill)}
                                onShare={() => onShare(skill)}
                                onDelete={() => onDelete(skill)}
                            />
                            {isExpanded && (
                                <SkillRowExpansion skillId={skill.id} onOpenEditor={() => onOpenEditor(skill)} />
                            )}
                        </div>
                    );
                })}
            </div>
        </section>
    );
}

function Stat({ label, value }: { label: string; value: number }) {
    return (
        <div className="px-2.5 py-1 rounded-lg border border-border dark:border-white/[0.06] bg-foreground/[0.03]">
            <div className="text-[9px] text-muted-foreground/70 dark:text-white/40 uppercase tracking-wide">{label}</div>
            <div className="text-xs font-medium text-foreground leading-tight">{value}</div>
        </div>
    );
}

function Empty({
    title,
    description,
    action,
}: {
    title: string;
    description?: string;
    action?: { label: string; onClick: () => void };
}) {
    return (
        <div className="text-center py-16">
            <div className="mx-auto h-10 w-10 rounded-lg bg-foreground/[0.05] border border-border dark:border-white/[0.08] flex items-center justify-center mb-3">
                <Brain className="h-5 w-5 text-muted-foreground dark:text-white/60" />
            </div>
            <div className="text-sm text-foreground font-medium">{title}</div>
            {description && <div className="text-xs text-muted-foreground/70 dark:text-white/40 mt-1 max-w-md mx-auto">{description}</div>}
            {action && (
                <button
                    onClick={action.onClick}
                    className="mt-4 inline-flex items-center gap-1.5 h-9 px-4 text-sm font-medium bg-primary text-primary-foreground rounded-lg hover:bg-foreground/90 transition-colors"
                >
                    {action.label}
                </button>
            )}
        </div>
    );
}

function CreateSkillDialog({
    isInternal,
    onCancel,
    onCreated,
}: {
    isInternal: boolean;
    onCancel: () => void;
    onCreated: (skillId: string) => void;
}) {
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [isSystem, setIsSystem] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const submit = () => {
        if (!name.trim()) {
            setError('Name is required');
            return;
        }
        setBusy(true);
        setError(null);
        sendEventWithCallback(
            {
                event_name: 'skill:create',
                name: name.trim(),
                description: description.trim(),
                body_text: null,
                enabled: true,
                is_system: isSystem,
            } as any,
            (resp: any) => {
                setBusy(false);
                if (resp?.error) {
                    setError(resp.error);
                    return;
                }
                if (resp.skill?.id) onCreated(resp.skill.id);
            },
        );
    };

    return (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
            <div className="bg-sunken border border-border dark:border-white/[0.08] rounded-xl w-full max-w-md shadow-2xl">
                <div className="flex items-center justify-between border-b border-border dark:border-white/[0.06] px-4 py-3">
                    <span className="text-sm font-semibold text-foreground">New skill</span>
                    <button onClick={onCancel} className="text-muted-foreground/70 dark:text-white/40 hover:text-foreground/80">
                        <X className="h-4 w-4" />
                    </button>
                </div>
                <div className="p-4 space-y-3">
                    <div>
                        <div className="text-xs font-medium text-muted-foreground dark:text-white/50 mb-1.5">Name</div>
                        <input
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            placeholder="e.g. Apple-style copy guidelines"
                            className="w-full h-9 px-3 text-sm bg-background/40 border border-border dark:border-white/[0.08] rounded-lg text-foreground placeholder-foreground/20 outline-none focus:border-foreground/20"
                            autoFocus
                        />
                    </div>
                    <div>
                        <div className="text-xs font-medium text-muted-foreground dark:text-white/50 mb-1.5">Description</div>
                        <textarea
                            value={description}
                            onChange={(e) => setDescription(e.target.value)}
                            rows={3}
                            placeholder="When should the agent load this skill?"
                            className="w-full bg-background/40 border border-border dark:border-white/[0.08] focus:border-foreground/20 rounded-lg px-3 py-2 text-sm text-foreground placeholder-foreground/20 resize-y focus:outline-none"
                        />
                    </div>
                    {isInternal && (
                        <label className="flex items-center gap-2 text-xs text-muted-foreground dark:text-white/60">
                            <input
                                type="checkbox"
                                checked={isSystem}
                                onChange={(e) => setIsSystem(e.target.checked)}
                                className="accent-primary"
                            />
                            Mark as system (loaded into every internal builder call)
                        </label>
                    )}
                    {error && (
                        <div className="text-xs text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/50 rounded-lg px-3 py-2">
                            {error}
                        </div>
                    )}
                </div>
                <div className="flex items-center justify-end gap-2 border-t border-border dark:border-white/[0.06] px-4 py-3">
                    <button
                        onClick={onCancel}
                        className="h-9 px-3 text-sm font-medium bg-foreground/[0.05] border border-border dark:border-white/[0.08] hover:bg-foreground/[0.08] hover:border-muted-foreground/30 dark:hover:border-white/[0.12] text-foreground/80 rounded-lg transition-colors"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={submit}
                        disabled={busy || !name.trim()}
                        className="h-9 px-4 text-sm font-medium bg-primary text-primary-foreground rounded-lg hover:bg-foreground/90 disabled:opacity-40 transition-colors"
                    >
                        {busy ? 'Creating…' : 'Create & open'}
                    </button>
                </div>
            </div>
        </div>
    );
}
