// What a skill's or memory's page does to it besides its sections: attach it to more agents (or take it off one),
// download it, rename it, and move it to the trash naming every agent it's detached from.
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Check, Download, MoreHorizontal, Pencil, Plus, Trash2 } from 'lucide-react';
import { useWorkClient } from '../../client';
import { invalidateV1 } from '@/sdk/useV1';
import { memoryEntries, previewTrash, readSkillFile, renameKnowledge, trashKnowledge, type Knowledge } from '@/screens/resources/knowledge';
import { BUTTON_DANGER, BUTTON_GHOST, BUTTON_PRIMARY } from '@/ui/buttons';
import { FIELD_LABEL } from '@/ui/fields';
import { MENU_SURFACE } from '@/ui/menus';
import { ShellDialog } from '@/ui/ShellDialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/ui/dropdown-menu';
import { cn } from '@/ui/utils';
import { setMode, useMode } from './mode';
import { AgentFace, ICON_BUTTON, list, MENU_ITEM, MENU_RULE, PILL_FIELD, SMALL_SECONDARY } from './parts';
import { attach, detachWithUndo, memoryRefusal, MEMORIES_KEY, readLinksAgain, SKILLS_KEY, titleOf, useKnowledge } from './store';

/** Attach it to more agents, or take it off one: every agent of the account, those that can't have it greyed with why. */
export function AttachToMenu({ item }: { item: Knowledge }) {
    const client = useWorkClient();
    const k = useKnowledge();
    const using = new Set(k.usersOf(item).map((u) => u.agent.id));
    const owner = item.kind === 'memory' && item.agentId ? k.agent(item.agentId) : undefined;
    return (
        <DropdownMenu>
            <DropdownMenuTrigger className={cn(SMALL_SECONDARY, 'data-[state=open]:bg-accent')}>
                <Plus className="h-4 w-4" strokeWidth={2} />
                Attach to
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" sideOffset={6} className={cn('max-h-[min(26rem,var(--radix-dropdown-menu-content-available-height))] w-[290px] overflow-y-auto rounded-xl p-1', MENU_SURFACE)}>
                <DropdownMenuLabel className="px-2.5 pb-1 pt-1.5 text-xs font-normal text-muted-foreground">Agents of the account</DropdownMenuLabel>
                {k.agents.map((a) => {
                    const on = using.has(a.id);
                    const home = item.kind === 'memory' && item.agentId === a.id;
                    const refusal = on ? null : memoryRefusal(a, item);
                    return (
                        <DropdownMenuItem
                            key={a.id}
                            disabled={home || !!refusal}
                            onSelect={(e) => {
                                e.preventDefault();
                                if (on) void detachWithUndo(client, a, item, titleOf(item, owner));
                                else void attach(client, a, item, item.kind === 'memory' ? { writes: false } : {});
                            }}
                            className="gap-2.5 rounded-lg px-2.5 py-2"
                        >
                            <AgentFace agent={a} size={24} />
                            <span className="min-w-0 flex-1">
                                <span className="block text-[14px]">{a.name}</span>
                                {(home || refusal) && <span className="block truncate text-xs text-muted-foreground">{home ? 'Its own: always attached' : refusal}</span>}
                            </span>
                            <Check className={cn('h-4 w-4 shrink-0', on ? 'opacity-100' : 'opacity-0')} strokeWidth={2} />
                        </DropdownMenuItem>
                    );
                })}
                {!k.agents.length && <p className="px-2.5 py-2 text-[13px] text-muted-foreground">The account has no agent yet.</p>}
            </DropdownMenuContent>
        </DropdownMenu>
    );
}

function save(name: string, text: string, type: string) {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const a = Object.assign(document.createElement('a'), { href: url, download: name });
    a.click();
    URL.revokeObjectURL(url);
}

/** Its SKILL.md, or a memory's entries as one Markdown file. */
export async function downloadKnowledge(client: ReturnType<typeof useWorkClient>, item: Knowledge, title: string): Promise<void> {
    try {
        if (item.kind === 'skill') {
            const file = await readSkillFile(client, item.id, 'SKILL.md', item.version);
            save(`${item.name}.md`, file.content, 'text/markdown');
            return;
        }
        const entries = await memoryEntries(client, item.id);
        const body = entries.map((e) => `## ${e.name}\n\n${e.description}\n\n${e.content ?? ''}`.trimEnd()).join('\n\n');
        save(`${(item.name ?? title).replace(/[^\w.-]+/g, '-')}.md`, `# ${title}\n\n${item.description}\n\n${body}\n`, 'text/markdown');
    } catch (error) {
        toast.error('Couldn’t download it', { description: error instanceof Error ? error.message : String(error) });
    }
}

/** Its head's actions, as every page of one draws them: Edit (a skill) or New entry (a memory), Attach to, and its ⋯. */
export function KnowledgeHeadActions({ item, onTrashed, trash = true }: { item: Knowledge; onTrashed?: () => void; trash?: boolean }) {
    const mode = useMode(item.id);
    return (
        <>
            {item.kind === 'skill' ? (
                <button type="button" disabled={mode === 'editing'} onClick={() => setMode(item.id, 'editing')} className={SMALL_SECONDARY}>
                    <Pencil className="h-3.5 w-3.5" strokeWidth={2} />
                    Edit
                </button>
            ) : (
                <button type="button" disabled={mode === 'writing'} onClick={() => setMode(item.id, 'writing')} className={SMALL_SECONDARY}>
                    <Plus className="h-3.5 w-3.5" strokeWidth={2} />
                    New entry
                </button>
            )}
            <AttachToMenu item={item} />
            <KnowledgeMore item={item} onTrashed={onTrashed} trash={trash} />
        </>
    );
}

/** Its page's ⋯: download, rename, and (under a rule, in red) the trash; an agent's own memory goes only with its agent. */
export function KnowledgeMore({ item, onTrashed, trash = true }: { item: Knowledge; onTrashed?: () => void; trash?: boolean }) {
    const client = useWorkClient();
    const k = useKnowledge();
    const owner = item.kind === 'memory' && item.agentId ? k.agent(item.agentId) : undefined;
    const title = titleOf(item, owner);
    const [asked, setAsked] = useState<'rename' | 'trash' | null>(null);
    return (
        <>
            <DropdownMenu>
                <DropdownMenuTrigger aria-label="More" className={cn(ICON_BUTTON, 'h-9 w-9 bg-foreground/[0.05] data-[state=open]:bg-foreground/[0.09] data-[state=open]:text-foreground')}>
                    <MoreHorizontal className="h-[18px] w-[18px]" />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" sideOffset={6} className={cn('w-[240px] rounded-xl p-1', MENU_SURFACE)}>
                    {!owner && (
                        <DropdownMenuItem onSelect={() => setAsked('rename')} className={MENU_ITEM}>
                            <Pencil className="h-4 w-4 text-muted-foreground" strokeWidth={1.75} />
                            Rename
                        </DropdownMenuItem>
                    )}
                    <DropdownMenuItem onSelect={() => void downloadKnowledge(client, item, title)} className={MENU_ITEM}>
                        <Download className="h-4 w-4 text-muted-foreground" strokeWidth={1.75} />
                        {item.kind === 'skill' ? 'Download SKILL.md' : 'Download as Markdown'}
                    </DropdownMenuItem>
                    {!owner && trash && (
                        <>
                            <DropdownMenuSeparator className={MENU_RULE} />
                            <DropdownMenuItem onSelect={() => setAsked('trash')} className={cn(MENU_ITEM, 'text-red-600 focus:bg-red-500/10 focus:text-red-600 dark:text-red-400 dark:focus:text-red-400')}>
                                <Trash2 className="h-4 w-4" strokeWidth={1.75} />
                                Move to the trash
                            </DropdownMenuItem>
                        </>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
            {asked === 'rename' && <RenameDialog item={item} onClose={() => setAsked(null)} />}
            {asked === 'trash' && (
                <TrashDialog
                    item={item}
                    onClose={(gone) => {
                        setAsked(null);
                        if (gone) onTrashed?.();
                    }}
                />
            )}
        </>
    );
}

const NAME_RULE = { skill: /^[a-z0-9]+(-[a-z0-9]+)*$/, memory: /^[a-z0-9._-]{1,64}$/ } as const;

export function RenameDialog({ item, onClose }: { item: Knowledge; onClose: () => void }) {
    const client = useWorkClient();
    const [name, setName] = useState(item.name ?? '');
    const [busy, setBusy] = useState(false);
    const valid = name.length <= 64 && NAME_RULE[item.kind].test(name) && name !== item.name;
    const rename = async () => {
        setBusy(true);
        try {
            await renameKnowledge(client, item, name);
            invalidateV1(item.kind === 'skill' ? SKILLS_KEY : MEMORIES_KEY);
            readLinksAgain();
            onClose();
        } catch (error) {
            toast.error('Couldn’t rename it', { description: error instanceof Error ? error.message : String(error) });
            setBusy(false);
        }
    };
    return (
        <ShellDialog
            open
            onOpenChange={(o) => !o && onClose()}
            title={`Rename ${item.name}`}
            description={item.kind === 'skill' ? 'Its SKILL.md takes the new name, as a new version. Agents see it from their next conversation.' : 'Agents see the new name from their next turn.'}
            mark={<Pencil className="h-5 w-5" strokeWidth={1.75} />}
            onSubmit={(e) => {
                e.preventDefault();
                if (valid && !busy) void rename();
            }}
            footer={
                <>
                    <button type="button" onClick={onClose} className={BUTTON_GHOST}>
                        Cancel
                    </button>
                    <button type="submit" disabled={!valid || busy} className={BUTTON_PRIMARY}>
                        Rename
                    </button>
                </>
            }
        >
            <label className="block pb-1">
                <span className={FIELD_LABEL}>Name</span>
                <input
                    value={name}
                    onChange={(e) => setName(e.target.value.toLowerCase().replace(item.kind === 'skill' ? /[^a-z0-9-]/g : /[^a-z0-9._-]/g, '-'))}
                    className={cn(PILL_FIELD, 'font-mono text-[13px]')}
                />
            </label>
        </ShellDialog>
    );
}

/** To the trash, naming the agents it's detached from (the platform's own preview); restored, they get it back. */
export function TrashDialog({ item, onClose }: { item: Knowledge; onClose: (gone: boolean) => void }) {
    const client = useWorkClient();
    const k = useKnowledge();
    const users = k.usersOf(item).filter((u) => u.link);
    const [busy, setBusy] = useState(false);
    const [impact, setImpact] = useState<string | null>(null);
    useEffect(() => {
        let live = true;
        previewTrash(client, item)
            .then((p) => live && setImpact(p.deletes))
            .catch((error: unknown) => console.warn('[resources] the trash preview failed:', error));
        return () => {
            live = false;
        };
    }, [client, item]);
    const confirm = async () => {
        setBusy(true);
        try {
            const trashed = await trashKnowledge(client, item);
            invalidateV1(item.kind === 'skill' ? SKILLS_KEY : MEMORIES_KEY);
            readLinksAgain();
            invalidateV1('resources:trash');
            onClose(true);
            toast(`${item.name} is in the trash`, {
                description: users.length ? `Detached from ${list(users.map((u) => u.agent.name))}. Restore it within 30 days to put it back.` : 'Restore it within 30 days.',
                action: {
                    label: 'Undo',
                    onClick: () =>
                        void trashed.restore().then(() => {
                            invalidateV1(item.kind === 'skill' ? SKILLS_KEY : MEMORIES_KEY);
                            readLinksAgain();
                            invalidateV1('resources:trash');
                        }),
                },
            });
        } catch (error) {
            toast.error('Couldn’t move it to the trash', { description: error instanceof Error ? error.message : String(error) });
            setBusy(false);
        }
    };
    return (
        <ShellDialog
            open
            onOpenChange={(o) => !o && onClose(false)}
            tone="danger"
            title={`Move ${item.name} to the trash?`}
            description={impact ?? 'It goes to the account’s trash for 30 days, detached from every agent.'}
            mark={<Trash2 className="h-5 w-5" strokeWidth={1.75} />}
            testId="knowledge-trash"
            footer={
                <>
                    <button type="button" onClick={() => onClose(false)} className={BUTTON_GHOST}>
                        Cancel
                    </button>
                    <button type="button" disabled={busy} onClick={() => void confirm()} className={BUTTON_DANGER}>
                        Move to the trash
                    </button>
                </>
            }
        >
            <div className="flex flex-col gap-3 pb-1 text-[13.5px]">
                {users.length > 0 ? (
                    <div>
                        <p className="mb-1.5 text-[12.5px] text-muted-foreground">Detached from</p>
                        <ul className="flex flex-col gap-1.5">
                            {users.map((u) => (
                                <li key={u.agent.id} className="flex items-center gap-2.5">
                                    <AgentFace agent={u.agent} size={20} />
                                    <span className="font-medium">{u.agent.name}</span>
                                </li>
                            ))}
                        </ul>
                    </div>
                ) : (
                    <p className="text-muted-foreground">No agent uses it.</p>
                )}
                <p className="text-muted-foreground">Restoring it from the trash attaches it again.</p>
            </div>
        </ShellDialog>
    );
}
