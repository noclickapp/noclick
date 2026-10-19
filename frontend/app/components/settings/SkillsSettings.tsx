// Skills management for the Settings page.
// User-facing surface for creating, sharing, and toggling skills — built to mirror
// the visual language of DeveloperSettings (muted panels, muted-foreground hints,
// flat row layout, primary button) so it sits consistently in Settings.

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
    Plus,
    Share2,
    Trash2,
    Workflow as WorkflowIcon,
    FileText,
    ShieldCheck,
    Lock,
} from 'lucide-react';
import { sendEventWithCallback } from '~/lib/socket-sender';
import { cn } from '~/lib/utils';
import { BUTTON_PRIMARY } from '~/components/shell/buttons';
import { FIELD, FIELD_LABEL } from '~/components/shell/fields';
import { SettingsEmpty, SettingsGroup, SettingsGroupTitle, SettingsHeader } from '~/components/settings/SettingsParts';
import { ShareDialog } from '~/components/shared/popups/ShareDialog';
import { DeleteConfirmPopup } from '~/components/shared/popups/DeleteConfirmPopup';
import { SkillEditor } from '~/components/skills/SkillEditor';
import { canDeleteSkill, canEditSkill, type SkillListResponse, type SkillScope, type SkillSummary } from '~/components/skills/skillTypes';

type EditorState = { skillId: string; scope: SkillScope } | null;
type ShareState = { skill: SkillSummary } | null;
type DeleteState = { skill: SkillSummary } | null;

export function SkillsSettings() {
    const [owned, setOwned] = useState<SkillSummary[]>([]);
    const [shared, setShared] = useState<SkillSummary[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const [newName, setNewName] = useState('');
    const [creating, setCreating] = useState(false);
    const [editor, setEditor] = useState<EditorState>(null);
    const [share, setShare] = useState<ShareState>(null);
    const [pendingDelete, setPendingDelete] = useState<DeleteState>(null);

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
            },
        );
    }, []);

    useEffect(() => {
        fetchList();
    }, [fetchList]);

    const handleCreate = useCallback(() => {
        if (!newName.trim()) return;
        setCreating(true);
        sendEventWithCallback(
            {
                event_name: 'skill:create',
                name: newName.trim(),
                description: '',
                body_text: null,
                enabled: true,
                is_system: false,
            } as any,
            (resp: any) => {
                setCreating(false);
                if (resp?.error) {
                    setError(resp.error);
                    return;
                }
                setNewName('');
                fetchList();
                if (resp.skill?.id) setEditor({ skillId: resp.skill.id, scope: 'owned' });
            },
        );
    }, [newName, fetchList]);

    // The single row toggle = "is this skill active for me right now?".
    // For owned skills, that's the owner-side `enabled` flag. For shared skills
    // (where the user can't change `enabled`), the same control toggles the
    // per-user mute. The visual semantics are identical from the user's POV.
    const toggleActive = useCallback((skill: SkillSummary, scope: SkillScope) => {
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
    }, [fetchList]);

    const confirmDelete = useCallback((skill: SkillSummary) => {
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
    }, [fetchList]);

    // System skills are intentionally hidden from the user-facing Settings surface.
    // They're managed from the internal Debug → Skills tab only.
    const sections = useMemo<Array<{ title: string; scope: SkillScope; skills: SkillSummary[]; help?: string }>>(() => {
        const out: Array<{ title: string; scope: SkillScope; skills: SkillSummary[]; help?: string }> = [];
        out.push({ title: 'Your skills', scope: 'owned', skills: owned, help: 'Skills you authored, including those scoped to your active workspace.' });
        if (shared.length) {
            out.push({ title: 'Shared with me', scope: 'shared', skills: shared, help: 'Skills shared via resource sharing — view-only by default.' });
        }
        return out;
    }, [owned, shared]);

    const totalCount = owned.length + shared.length;

    // Editor mode replaces the list in-place so the Settings chrome stays visible
    // (sidebar nav, page padding) — no fullscreen overlay.
    if (editor) {
        return (
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
        );
    }

    return (
        <div>
            <SettingsHeader
                title="Skills"
                description="Reusable agent context: a description plus optional text and a workflow body. Enabled skills are loaded into every builder call so the agent can use them on demand."
            />

            {/* Error banner */}
            {error && (
                <div className="mb-4 px-4 py-3 bg-red-500/10 border border-red-500/30 rounded-xl text-sm text-red-700 dark:text-red-300 flex items-center justify-between">
                    <span>{error}</span>
                    <button onClick={() => setError(null)} className="text-red-600/70 hover:text-red-700 dark:text-red-400/60 dark:hover:text-red-300 text-xs">
                        Dismiss
                    </button>
                </div>
            )}

            {/* Create new skill */}
            <div className="mb-8">
                <label htmlFor="new-skill-name" className={FIELD_LABEL}>Skill name</label>
                <div className="flex items-center gap-2.5">
                    <input
                        id="new-skill-name"
                        value={newName}
                        onChange={(e) => setNewName(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
                        placeholder="e.g. Apple-style copy guidelines"
                        className={FIELD}
                    />
                    <button onClick={handleCreate} disabled={creating || !newName.trim()} className={cn(BUTTON_PRIMARY, 'h-10 px-4')}>
                        <Plus className="w-4 h-4" />
                        Create
                    </button>
                </div>
            </div>

            {/* List */}
            {loading && totalCount === 0 ? (
                <SettingsGroup>
                    <SettingsEmpty>Loading…</SettingsEmpty>
                </SettingsGroup>
            ) : totalCount === 0 ? (
                <SettingsGroup>
                    <SettingsEmpty>No skills yet. Create one above to give the agent persistent context.</SettingsEmpty>
                </SettingsGroup>
            ) : (
                <div className="space-y-8">
                    {sections.map((section) => (
                        <div key={section.scope}>
                            <SettingsGroupTitle
                                title={
                                    <>
                                        {section.title} <span className="ml-1 font-normal tabular-nums text-muted-foreground">{section.skills.length}</span>
                                    </>
                                }
                                description={section.help}
                            />
                            <SettingsGroup>
                                {section.skills.map((skill) => (
                                    <SkillRowCompact
                                        key={skill.id}
                                        skill={skill}
                                        scope={section.scope}
                                        onClick={() => setEditor({ skillId: skill.id, scope: section.scope })}
                                        onToggleActive={() => toggleActive(skill, section.scope)}
                                        onShare={() => setShare({ skill })}
                                        onDelete={() => setPendingDelete({ skill })}
                                    />
                                ))}
                            </SettingsGroup>
                        </div>
                    ))}
                </div>
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

function SkillRowCompact({
    skill,
    scope,
    onClick,
    onToggleActive,
    onShare,
    onDelete,
}: {
    skill: SkillSummary;
    scope: SkillScope;
    onClick: () => void;
    onToggleActive: () => void;
    onShare: () => void;
    onDelete: () => void;
}) {
    const editable = canEditSkill(skill, scope);
    const deletable = canDeleteSkill(skill, scope);
    const shareable = scope === 'owned' && !skill.is_system;
    // Active = "this skill is loaded into builder calls for me right now".
    // For owned skills that's the owner-side `enabled` flag; for shared skills
    // it's the inverse of the per-user mute (since the viewer can't change `enabled`).
    const active = scope === 'shared' ? !skill.muted : skill.enabled;
    const toggleTitle = scope === 'shared'
        ? (active ? 'Mute for me' : 'Unmute')
        : (active ? 'Disable' : 'Enable');

    return (
        <div
            role="button"
            tabIndex={0}
            onClick={onClick}
            onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onClick();
                }
            }}
            className={cn('group flex min-h-[64px] cursor-pointer items-center gap-4 px-5 py-3.5 transition-colors hover:bg-foreground/[0.03]', !active && 'opacity-60')}
        >
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                    <span className="truncate text-[14.5px] font-medium text-foreground">{skill.name || 'Untitled skill'}</span>
                    {skill.is_system && <Pill icon={ShieldCheck} tone="violet">System</Pill>}
                    {skill.has_workflow && <Pill icon={WorkflowIcon} tone="indigo">Workflow</Pill>}
                    {skill.has_text && <Pill icon={FileText} tone="zinc">Text</Pill>}
                    {!editable && <Pill icon={Lock} tone="zinc">Read-only</Pill>}
                </div>
                {skill.description ? (
                    <div className="mt-0.5 line-clamp-1 text-[13px] text-muted-foreground">{skill.description}</div>
                ) : (
                    <div className="mt-0.5 text-[13px] text-muted-foreground/60">No description</div>
                )}
            </div>
            <div className="flex items-center gap-1 shrink-0">
                <SwitchControl
                    enabled={active}
                    onChange={(e) => {
                        e.stopPropagation();
                        onToggleActive();
                    }}
                    title={toggleTitle}
                />
                {shareable && (
                    <IconBtn
                        title="Share"
                        onClick={(e) => {
                            e.stopPropagation();
                            onShare();
                        }}
                    >
                        <Share2 className="w-4 h-4" />
                    </IconBtn>
                )}
                {deletable && (
                    <IconBtn
                        title="Delete"
                        danger
                        onClick={(e) => {
                            e.stopPropagation();
                            onDelete();
                        }}
                    >
                        <Trash2 className="w-4 h-4" />
                    </IconBtn>
                )}
            </div>
        </div>
    );
}

function IconBtn({
    children,
    onClick,
    title,
    danger,
}: {
    children: React.ReactNode;
    onClick: (e: React.MouseEvent) => void;
    title: string;
    danger?: boolean;
}) {
    return (
        <button
            onClick={onClick}
            title={title}
            className={`p-2 rounded-lg transition-colors ${
                danger
                    ? 'text-muted-foreground/50 dark:text-white/20 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-500/10'
                    : 'text-muted-foreground/70 dark:text-white/30 hover:text-foreground/80 hover:bg-foreground/[0.05]'
            }`}
        >
            {children}
        </button>
    );
}

function SwitchControl({
    enabled,
    disabled,
    onChange,
    title,
}: {
    enabled: boolean;
    disabled?: boolean;
    onChange: (e: React.MouseEvent) => void;
    title: string;
}) {
    return (
        <button
            type="button"
            onClick={(e) => {
                if (disabled) return;
                onChange(e);
            }}
            title={title}
            disabled={disabled}
            aria-pressed={enabled}
            className={`relative inline-flex shrink-0 mx-1 h-5 w-9 rounded-full border transition-colors ${
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

// Tags stay quiet; only amber (a warning) keeps its colour.
const pillTone: Record<string, string> = {
    violet: 'bg-foreground/[0.06] text-foreground/75',
    indigo: 'bg-foreground/[0.06] text-foreground/75',
    amber: 'bg-amber-500/10 text-amber-700 dark:text-amber-300',
    zinc: 'bg-foreground/[0.05] text-muted-foreground',
};

function Pill({
    children,
    tone,
    icon: Icon,
}: {
    children: React.ReactNode;
    tone: 'violet' | 'indigo' | 'amber' | 'zinc';
    icon?: React.ComponentType<{ className?: string }>;
}) {
    return (
        <span
            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11.5px] font-medium ${pillTone[tone]}`}
        >
            {Icon && <Icon className="h-3 w-3" />}
            {children}
        </span>
    );
}
