// Settings → Skills: the skills NoClick's builder loads for the account, made by name, each turned on or off with the
// product's switch (its own `enabled`, or its mute where it's shared with the account), opened in the editor a host
// fills (EDITOR; the standard edits its words), shared where a host fills SHARE, and deleted. `SkillsSection` is the
// section over its read (skillReads.ts).
import { useState, type ComponentType, type ReactNode } from 'react';
import { FileText, Lock, Plus, Share2, Trash2, Workflow as WorkflowIcon } from 'lucide-react';
import type { BuilderSkill } from 'noclick';
import { useSlot } from '@/slots';
import { BUTTON_PRIMARY } from '@/ui/buttons';
import { DeleteConfirmPopup } from '@/ui/DeleteConfirmPopup';
import { FIELD, FIELD_LABEL } from '@/ui/fields';
import { Switch } from '@/ui/switch';
import { cn } from '@/ui/utils';
import { SettingsEmpty, SettingsGroup, SettingsGroupTitle, SettingsHeader } from './parts';
import { useBuilderSkills } from './skillReads';
import { SKILL_EDITOR, SKILL_SHARE } from './slots';

type Scope = BuilderSkill['scope'];

/** The editor a host draws in place of the list for one skill: `onChanged` after a save, `onClose` when it's left. */
export type SkillEditorProps = { skillId: string; scope: Scope; onClose: () => void; onChanged: () => void };
/** A host's way to share one skill, open while `skill` is set. */
export type SkillShareProps = { skill: { id: string; name: string } | null; onClose: () => void };

const SECTIONS: { title: string; scope: Scope; help: string }[] = [
    { title: 'Your skills', scope: 'owned', help: 'Skills you authored, including those scoped to your active workspace.' },
    { title: 'Shared with me', scope: 'shared', help: 'Skills shared via resource sharing — view-only by default.' },
];

export function SkillsSection() {
    const skills = useBuilderSkills();
    const Editor = useSlot(SKILL_EDITOR) as ComponentType<SkillEditorProps>;
    const Share = useSlot(SKILL_SHARE) as ComponentType<SkillShareProps> | null;
    const [newName, setNewName] = useState('');
    const [creating, setCreating] = useState(false);
    const [editing, setEditing] = useState<{ skillId: string; scope: Scope } | null>(null);
    const [sharing, setSharing] = useState<BuilderSkill | null>(null);
    const [deleting, setDeleting] = useState<BuilderSkill | null>(null);

    const create = async () => {
        if (!newName.trim()) return;
        setCreating(true);
        const made = await skills.create(newName.trim());
        setCreating(false);
        if (!made) return;
        setNewName('');
        setEditing({ skillId: made.id, scope: 'owned' });
    };

    // The editor replaces the list in place, so Settings' frame stays around it.
    if (editing) {
        return (
            <Editor
                skillId={editing.skillId}
                scope={editing.scope}
                onClose={() => {
                    setEditing(null);
                    skills.refresh();
                }}
                onChanged={skills.refresh}
            />
        );
    }

    const owned = skills.owned ?? [];
    const shared = skills.shared ?? [];
    const total = owned.length + shared.length;
    const loading = skills.owned === null && !skills.error;
    const sections = SECTIONS.map((s) => ({ ...s, skills: s.scope === 'owned' ? owned : shared })).filter((s) => s.scope === 'owned' || s.skills.length);

    return (
        <div>
            <SettingsHeader
                title="Skills"
                description="Reusable agent context: a description plus optional text and a workflow body. Enabled skills are loaded into every builder call so the agent can use them on demand."
            />

            {skills.error && (
                <div className="mb-4 px-4 py-3 bg-red-500/10 border border-red-500/30 rounded-xl text-sm text-red-700 dark:text-red-300 flex items-center justify-between">
                    <span>{skills.error}</span>
                    <button onClick={skills.dismissError} className="text-red-600/70 hover:text-red-700 dark:text-red-400/60 dark:hover:text-red-300 text-xs">
                        Dismiss
                    </button>
                </div>
            )}

            <div className="mb-8">
                <label htmlFor="new-skill-name" className={FIELD_LABEL}>
                    Skill name
                </label>
                <div className="flex items-center gap-2.5">
                    <input
                        id="new-skill-name"
                        value={newName}
                        onChange={(e) => setNewName(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && void create()}
                        placeholder="e.g. Apple-style copy guidelines"
                        className={FIELD}
                    />
                    <button onClick={() => void create()} disabled={creating || !newName.trim()} className={cn(BUTTON_PRIMARY, 'h-10 px-4')}>
                        <Plus className="w-4 h-4" />
                        Create
                    </button>
                </div>
            </div>

            {loading && total === 0 ? (
                <SettingsGroup>
                    <SettingsEmpty>Loading…</SettingsEmpty>
                </SettingsGroup>
            ) : total === 0 ? (
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
                                    <SkillRow
                                        key={skill.id}
                                        skill={skill}
                                        onOpen={() => setEditing({ skillId: skill.id, scope: section.scope })}
                                        onToggleActive={() => void skills.toggleActive(skill)}
                                        onShare={Share ? () => setSharing(skill) : null}
                                        onDelete={() => setDeleting(skill)}
                                    />
                                ))}
                            </SettingsGroup>
                        </div>
                    ))}
                </div>
            )}

            {Share && <Share skill={sharing && { id: sharing.id, name: sharing.name }} onClose={() => setSharing(null)} />}

            <DeleteConfirmPopup
                itemType="Skill"
                itemId={deleting?.id}
                itemName={deleting?.name}
                isOpen={!!deleting}
                onOpenChange={(open) => {
                    if (!open) setDeleting(null);
                }}
                onConfirmDelete={() => {
                    if (deleting) void skills.remove(deleting);
                }}
            />
        </div>
    );
}

/** One skill: its name with what it holds, its description, and its switch, share and delete; the row opens it. */
function SkillRow({
    skill,
    onOpen,
    onToggleActive,
    onShare,
    onDelete,
}: {
    skill: BuilderSkill;
    onOpen: () => void;
    onToggleActive: () => void;
    onShare: (() => void) | null;
    onDelete: () => void;
}) {
    // One shared with the account reads only; its switch is the account's own mute, since only its owner sets
    // `enabled`. The visual meaning is the same from the account's side.
    const own = skill.scope === 'owned';
    const active = own ? skill.enabled : !skill.muted;
    const toggleTitle = own ? (active ? 'Disable' : 'Enable') : active ? 'Mute for me' : 'Unmute';

    return (
        <div
            role="button"
            tabIndex={0}
            onClick={onOpen}
            onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onOpen();
                }
            }}
            className={cn('group flex min-h-[64px] cursor-pointer items-center gap-3 px-4 py-3.5 transition-colors hover:bg-foreground/[0.03] sm:gap-4 sm:px-5', !active && 'opacity-60')}
        >
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                    {/* Whole, wrapping beside the row's controls on a phone rather than cut short. */}
                    <span className="min-w-0 break-words text-[14.5px] font-medium text-foreground">{skill.name || 'Untitled skill'}</span>
                    {skill.hasWorkflow && <Pill icon={WorkflowIcon}>Workflow</Pill>}
                    {skill.hasText && (
                        <Pill icon={FileText} quiet>
                            Text
                        </Pill>
                    )}
                    {!own && (
                        <Pill icon={Lock} quiet>
                            Read-only
                        </Pill>
                    )}
                </div>
                {skill.description ? (
                    <div className="mt-0.5 line-clamp-2 text-[13px] text-muted-foreground sm:line-clamp-1">{skill.description}</div>
                ) : (
                    <div className="mt-0.5 text-[13px] text-muted-foreground/60">No description</div>
                )}
            </div>
            <div className="flex items-center gap-1 shrink-0">
                {/* The product's switch, its taps and keys its own: none reach the row, which opens the skill. */}
                <Switch
                    checked={active}
                    onCheckedChange={onToggleActive}
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => e.stopPropagation()}
                    aria-label={toggleTitle}
                    title={toggleTitle}
                    className="mx-1"
                />
                {own && onShare && (
                    <IconButton
                        title="Share"
                        onClick={(e) => {
                            e.stopPropagation();
                            onShare();
                        }}
                    >
                        <Share2 className="w-4 h-4" />
                    </IconButton>
                )}
                {own && (
                    <IconButton
                        title="Delete"
                        danger
                        onClick={(e) => {
                            e.stopPropagation();
                            onDelete();
                        }}
                    >
                        <Trash2 className="w-4 h-4" />
                    </IconButton>
                )}
            </div>
        </div>
    );
}

function IconButton({ children, onClick, title, danger }: { children: ReactNode; onClick: (e: React.MouseEvent) => void; title: string; danger?: boolean }) {
    return (
        <button
            onClick={onClick}
            title={title}
            className={`p-2 rounded-full transition-colors ${
                danger
                    ? 'text-muted-foreground/50 dark:text-white/20 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-500/10'
                    : 'text-muted-foreground/70 dark:text-white/30 hover:text-foreground/80 hover:bg-foreground/[0.05]'
            }`}
        >
            {children}
        </button>
    );
}

/** What a skill holds, quietly: a workflow, its text (quieter), or that it reads only (quieter). */
function Pill({ children, quiet, icon: Icon }: { children: ReactNode; quiet?: boolean; icon: ComponentType<{ className?: string }> }) {
    return (
        <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11.5px] font-medium ${quiet ? 'bg-foreground/[0.05] text-muted-foreground' : 'bg-foreground/[0.06] text-foreground/75'}`}>
            <Icon className="h-3 w-3" />
            {children}
        </span>
    );
}
