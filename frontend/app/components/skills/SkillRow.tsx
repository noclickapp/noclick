/**
 * SkillRow — single skill entry in the SkillsList (debug surface).
 * Click anywhere on the row to expand its inline preview; the action group on
 * the right offers a pencil to open the editor, the enable/mute toggle, share,
 * and delete. Settings uses its own simpler row in SkillsSettings.tsx where
 * the row click opens the editor directly.
 */

import { ChevronDown, ChevronRight, Workflow as WorkflowIcon, FileText, Trash2, Share2, ShieldCheck, Lock, Pencil } from 'lucide-react';
import { canDeleteSkill, canEditSkill, type SkillScope, type SkillSummary } from './skillTypes';

export function SkillRow({
    skill,
    scope,
    isExpanded,
    onOpenEditor,
    onToggleExpand,
    onToggleActive,
    onShare,
    onDelete,
}: {
    skill: SkillSummary;
    scope: SkillScope;
    isExpanded: boolean;
    onOpenEditor: () => void;
    onToggleExpand: () => void;
    onToggleActive: () => void;
    onShare: () => void;
    onDelete: () => void;
}) {
    const editable = canEditSkill(skill, scope);
    const deletable = canDeleteSkill(skill, scope);
    const shareable = scope === 'owned' && !skill.is_system;
    // Active = "this skill is loaded into builder calls for me right now".
    // Owned: owner-side `enabled`. Shared: inverse of per-user mute (since the
    // viewer can't change `enabled`). System skills always active for everyone.
    const active = scope === 'shared' ? !skill.muted : skill.enabled;
    const toggleTitle = scope === 'shared'
        ? (active ? 'Mute for me' : 'Unmute')
        : (active ? 'Disable' : 'Enable');

    return (
        <div
            role="button"
            tabIndex={0}
            onClick={onToggleExpand}
            onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onToggleExpand();
                }
            }}
            className={`group w-full text-left bg-foreground/[0.03] border border-border dark:border-white/[0.06] hover:bg-foreground/[0.05] hover:border-muted-foreground/30 dark:hover:border-white/[0.10] transition-colors cursor-pointer ${
                isExpanded ? 'rounded-t-xl border-b-0' : 'rounded-xl'
            } ${active ? '' : 'opacity-60'}`}
        >
            <div className="flex items-center gap-3 px-4 py-3">
                {/* Expand chevron — decorative; row click drives expansion. */}
                <span className="text-muted-foreground/70 dark:text-white/30 group-hover:text-foreground/60 transition-colors shrink-0" aria-hidden="true">
                    {isExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                </span>

                {/* Body */}
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-medium text-foreground truncate">{skill.name || 'Untitled skill'}</span>
                        {skill.is_system && <Pill tone="violet" icon={ShieldCheck}>System</Pill>}
                        {skill.has_workflow && <Pill tone="indigo" icon={WorkflowIcon}>Workflow</Pill>}
                        {skill.has_text && <Pill tone="zinc" icon={FileText}>Text</Pill>}
                        {!editable && <Pill tone="zinc" icon={Lock}>Read-only</Pill>}
                    </div>
                    {skill.description ? (
                        <p className="text-[12px] text-muted-foreground dark:text-white/40 mt-0.5 line-clamp-1 leading-relaxed">{skill.description}</p>
                    ) : (
                        <p className="text-[12px] text-muted-foreground/50 dark:text-white/20 mt-0.5 italic">No description</p>
                    )}
                </div>

                {/* Action group */}
                <div className="flex items-center gap-1 shrink-0">
                    <Switch
                        enabled={active}
                        disabled={skill.is_system}
                        onClick={(e) => {
                            e.stopPropagation();
                            if (skill.is_system) return;
                            onToggleActive();
                        }}
                        title={skill.is_system ? 'System skills are always active' : toggleTitle}
                    />
                    <IconAction
                        title={editable ? 'Edit skill' : 'Open skill'}
                        onClick={(e) => {
                            e.stopPropagation();
                            onOpenEditor();
                        }}
                    >
                        <Pencil className="h-4 w-4" />
                    </IconAction>
                    {shareable && (
                        <IconAction
                            title="Share"
                            onClick={(e) => {
                                e.stopPropagation();
                                onShare();
                            }}
                        >
                            <Share2 className="h-4 w-4" />
                        </IconAction>
                    )}
                    {deletable && (
                        <IconAction
                            title="Delete"
                            danger
                            onClick={(e) => {
                                e.stopPropagation();
                                onDelete();
                            }}
                        >
                            <Trash2 className="h-4 w-4" />
                        </IconAction>
                    )}
                </div>
            </div>
        </div>
    );
}

function IconAction({
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
            type="button"
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

export function Switch({
    enabled,
    disabled,
    onClick,
    title,
}: {
    enabled: boolean;
    disabled?: boolean;
    onClick: (e: React.MouseEvent) => void;
    title?: string;
}) {
    return (
        <button
            type="button"
            onClick={(e) => {
                if (disabled) return;
                onClick(e);
            }}
            disabled={disabled}
            aria-pressed={enabled}
            title={title}
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

const pillTone: Record<string, string> = {
    violet: 'bg-violet-500/10 text-violet-700 dark:text-violet-300 border-violet-500/30',
    indigo: 'bg-indigo-500/10 text-indigo-700 dark:text-indigo-300 border-indigo-500/30',
    zinc: 'bg-foreground/[0.05] text-muted-foreground dark:text-white/50 border-border dark:border-white/[0.08]',
};

function Pill({
    children,
    tone,
    icon: Icon,
}: {
    children: React.ReactNode;
    tone: 'violet' | 'indigo' | 'zinc';
    icon?: React.ComponentType<{ className?: string }>;
}) {
    return (
        <span
            className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md border text-[10px] font-medium uppercase tracking-wide ${pillTone[tone]}`}
        >
            {Icon && <Icon className="h-2.5 w-2.5" />}
            {children}
        </span>
    );
}
