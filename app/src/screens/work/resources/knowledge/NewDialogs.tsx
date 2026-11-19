// Making a skill (written here, or brought as a SKILL.md or its folder) or a memory (a name, the line agents see, and
// the agents that read or write it). What's made is the account's; `onClose` hands back the new one.
import { useRef, useState, type ChangeEvent } from 'react';
import { toast } from 'sonner';
import { BookOpen, Brain, Check, FolderUp } from 'lucide-react';
import { useWorkClient } from '../../client';
import { invalidateV1 } from '@/sdk/useV1';
import { createMemory, createSkill, frontmatter, setAgentLinks, skillMarkdown, type AgentRef, type Knowledge, type SkillFile } from '@/screens/resources/knowledge';
import { BUTTON_GHOST, BUTTON_PRIMARY } from '@/ui/buttons';
import { FIELD_LABEL } from '@/ui/fields';
import { ShellDialog } from '@/ui/ShellDialog';
import { cn } from '@/ui/utils';
import { DisabledTip } from '../../tooltip';
import { AgentFace, AREA, list, PILL_FIELD, SMALL_SECONDARY } from './parts';
import { MEMORIES_KEY, memoryRefusal, readLinksAgain, SKILLS_KEY, useKnowledge } from './store';

/** Agents to attach a new one to, as pills you tick; one that can't have it is greyed with why. */
function AgentPicks({ value, onChange, refusal }: { value: string[]; onChange: (v: string[]) => void; refusal?: (a: AgentRef) => string | null }) {
    const k = useKnowledge();
    if (!k.agents.length) return <p className="text-[13px] text-muted-foreground">The account has no agent yet: attach it to one later.</p>;
    return (
        <div className="flex flex-wrap gap-1.5">
            {k.agents.map((a) => {
                const on = value.includes(a.id);
                const no = refusal?.(a) ?? null;
                return (
                    <DisabledTip key={a.id} label={no} disabled={!!no && !on}>
                        <button
                            type="button"
                            disabled={!!no && !on}
                            aria-pressed={on}
                            onClick={() => onChange(on ? value.filter((v) => v !== a.id) : [...value, a.id])}
                            className={cn(
                                'inline-flex h-8 items-center gap-1.5 rounded-full pl-1 pr-3 text-[13px] ring-1 ring-inset transition-colors disabled:opacity-40',
                                on ? 'bg-foreground/[0.08] text-foreground ring-foreground/25' : 'text-muted-foreground ring-border hover:text-foreground dark:ring-foreground/[0.12]'
                            )}
                        >
                            <AgentFace agent={a} size={24} />
                            {a.name}
                            {on && <Check className="h-3.5 w-3.5" strokeWidth={2.5} />}
                        </button>
                    </DisabledTip>
                );
            })}
        </div>
    );
}

/** Attaches a new item to the agents picked, one call per agent; says who gets it. */
async function attachAll(client: ReturnType<typeof useWorkClient>, agents: AgentRef[], made: Knowledge, writes: boolean): Promise<string[]> {
    const done: string[] = [];
    for (const a of agents) {
        try {
            await setAgentLinks(client, a, made.kind === 'skill' ? { skills: [...a.skills, { id: made.id, pin: null }] } : { memories: [...a.memories, { id: made.id, writes }] });
            done.push(a.name);
        } catch (error) {
            toast.error(`Couldn’t attach it to ${a.name}`, { description: error instanceof Error ? error.message : String(error) });
        }
    }
    readLinksAgain();
    return done;
}

const SWITCH = 'mt-0.5 flex h-5 w-9 shrink-0 items-center rounded-full p-0.5 transition-colors';

function Toggle({ on, onChange, title, note }: { on: boolean; onChange: (on: boolean) => void; title: string; note: string }) {
    return (
        <button type="button" onClick={() => onChange(!on)} className="flex items-start gap-3 text-left" aria-pressed={on}>
            <span className={cn(SWITCH, on ? 'bg-foreground' : 'bg-foreground/15')}>
                <span className={cn('h-4 w-4 rounded-full bg-background transition-transform', on && 'translate-x-4')} />
            </span>
            <span>
                <span className="block text-sm">{title}</span>
                <span className="block text-xs text-muted-foreground">{note}</span>
            </span>
        </button>
    );
}

/** A skill's folder as picked: its files as the API takes them (text as is, anything else as base64). */
async function readPicked(picked: FileList): Promise<SkillFile[]> {
    const files = [...picked];
    // A folder's files carry its name first: the skill's own paths start inside it.
    const root = files[0]?.webkitRelativePath.includes('/') ? `${files[0].webkitRelativePath.split('/')[0]}/` : '';
    return Promise.all(
        files.map(async (f) => {
            const path = (f.webkitRelativePath || f.name).slice(root.length) || f.name;
            if (f.type.startsWith('text/') || /\.(md|txt|json|ya?ml|m?js|cjs|ts|py|sh|toml|csv)$/i.test(f.name)) return { path, content: await f.text() };
            const bytes = new Uint8Array(await f.arrayBuffer());
            let binary = '';
            for (const b of bytes) binary += String.fromCharCode(b);
            return { path, content: btoa(binary), encoding: 'base64' as const };
        })
    );
}

/** New skill: write it here, or bring one (a SKILL.md, or its folder with the scripts it uses). */
export function NewSkillDialog({ agent, onClose, inline }: { agent?: string; onClose: (created?: Knowledge) => void; inline?: boolean }) {
    const client = useWorkClient();
    const k = useKnowledge();
    const [how, setHow] = useState<'write' | 'import'>('write');
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [body, setBody] = useState('');
    const [always, setAlways] = useState(false);
    const [brought, setBrought] = useState<{ folder: string; files: SkillFile[] } | null>(null);
    const [agents, setAgents] = useState<string[]>(agent ? [agent] : []);
    const [busy, setBusy] = useState(false);
    const fileInput = useRef<HTMLInputElement>(null);
    const folderInput = useRef<HTMLInputElement>(null);
    const head = brought ? frontmatter(brought.files.find((f) => f.path === 'SKILL.md')?.content ?? '') : null;
    const valid =
        how === 'import'
            ? !!head?.name && !!head.description
            : /^[a-z0-9]+(-[a-z0-9]+)*$/.test(name) && name.length <= 64 && description.trim().length > 0 && !k.skills.some((s) => s.name === name);
    const pick = async (e: ChangeEvent<HTMLInputElement>) => {
        if (!e.target.files?.length) return;
        const files = await readPicked(e.target.files);
        const folder = e.target.files[0].webkitRelativePath.split('/')[0] || e.target.files[0].name;
        setBrought({ folder, files });
        e.target.value = '';
    };
    const create = async () => {
        setBusy(true);
        const files = how === 'import' ? brought!.files : [{ path: 'SKILL.md', content: skillMarkdown(name, description.trim(), body, always) }];
        try {
            const made = await createSkill(client, files);
            invalidateV1(SKILLS_KEY);
            const attached = await attachAll(client, k.agents.filter((a) => agents.includes(a.id)), made, false);
            toast(`${made.name} is in Resources`, {
                description: attached.length ? `${list(attached)} ${attached.length === 1 ? 'gets' : 'get'} it from the next conversation.` : 'Attach it to an agent when one needs it.',
            });
            onClose(made);
        } catch (error) {
            toast.error('Couldn’t make the skill', { description: error instanceof Error ? error.message : String(error) });
            setBusy(false);
        }
    };
    return (
        <ShellDialog
            open
            inline={inline}
            onOpenChange={(o) => !o && onClose()}
            title="New skill"
            description="A way of working any agent can follow: instructions, plus the scripts and files they use."
            mark={<BookOpen className="h-5 w-5" strokeWidth={1.75} />}
            size="md"
            testId="new-skill"
            footer={
                <div className="flex justify-end gap-2">
                    <button type="button" onClick={() => onClose()} className={BUTTON_GHOST}>
                        Cancel
                    </button>
                    <button type="button" disabled={!valid || busy} onClick={() => void create()} className={BUTTON_PRIMARY}>
                        Create skill
                    </button>
                </div>
            }
        >
            <div className="flex flex-col gap-4">
                <div className="flex gap-1">
                    {(
                        [
                            ['write', 'Write it'],
                            ['import', 'Bring one'],
                        ] as const
                    ).map(([id, label]) => (
                        <button
                            key={id}
                            type="button"
                            onClick={() => setHow(id)}
                            className={cn('h-8 rounded-full px-3 text-[13px] transition-colors', how === id ? 'bg-foreground/[0.08] font-medium text-foreground' : 'text-muted-foreground hover:text-foreground')}
                        >
                            {label}
                        </button>
                    ))}
                </div>
                {how === 'write' ? (
                    <>
                        <label>
                            <span className={FIELD_LABEL}>Name</span>
                            <input value={name} onChange={(e) => setName(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-'))} placeholder="refund-a-charge" className={cn(PILL_FIELD, 'font-mono text-[13px]')} />
                            {k.skills.some((s) => s.name === name) && <span className="mt-1.5 block text-[12.5px] text-red-600 dark:text-red-400">There’s a skill called that already.</span>}
                        </label>
                        <label>
                            <span className={FIELD_LABEL}>What it’s for</span>
                            <textarea
                                value={description}
                                onChange={(e) => setDescription(e.target.value)}
                                rows={2}
                                placeholder="Refund a customer’s charge through Stripe. Use when someone asks for money back."
                                className={AREA}
                            />
                            <span className="mt-1 block text-xs text-muted-foreground">Every agent that has it sees this line each turn: say what it does and when to use it.</span>
                        </label>
                        <label>
                            <span className={FIELD_LABEL}>Instructions</span>
                            <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={5} placeholder={'1. Find the charge by the customer’s email.\n2. …'} className={cn(AREA, 'font-mono text-[12.5px]')} />
                        </label>
                        <Toggle on={always} onChange={setAlways} title="In every turn" note="For a voice or rules every reply should follow. Otherwise an agent reads it when it’s needed." />
                    </>
                ) : brought ? (
                    <div className="rounded-xl bg-foreground/[0.04] px-4 py-3.5" data-testid="brought-skill">
                        <p className="flex items-center gap-2 text-sm font-medium">
                            <FolderUp className="h-4 w-4 text-muted-foreground" strokeWidth={1.75} />
                            {brought.folder}
                            <span className="font-normal text-muted-foreground">
                                · {brought.files.length} {brought.files.length === 1 ? 'file' : 'files'}
                            </span>
                        </p>
                        {head?.name ? (
                            <>
                                <p className="mt-2 font-mono text-[12.5px]">{head.name}</p>
                                <p className="mt-0.5 text-[13px] text-muted-foreground">{head.description}</p>
                            </>
                        ) : (
                            <p className="mt-2 text-[13px] text-red-600 dark:text-red-400">Its SKILL.md needs a name and a description at its top, between --- lines.</p>
                        )}
                        <p className="mt-2 text-xs text-muted-foreground">{brought.files.map((f) => f.path).join(' · ')}</p>
                        <button type="button" onClick={() => setBrought(null)} className={cn(SMALL_SECONDARY, 'mt-3')}>
                            Choose again
                        </button>
                    </div>
                ) : (
                    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-foreground/20 px-6 py-8 text-center">
                        <FolderUp className="h-6 w-6 text-muted-foreground" strokeWidth={1.5} />
                        <span className="text-sm">A SKILL.md, or a skill’s folder with its scripts</span>
                        <span className="mt-1 flex gap-2">
                            <button type="button" onClick={() => fileInput.current?.click()} className={SMALL_SECONDARY}>
                                Choose SKILL.md
                            </button>
                            <button type="button" onClick={() => folderInput.current?.click()} className={SMALL_SECONDARY}>
                                Choose a folder
                            </button>
                        </span>
                        <input ref={fileInput} type="file" accept=".md,text/markdown" hidden onChange={(e) => void pick(e)} data-testid="skill-file-input" />
                        <input ref={folderInput} type="file" hidden onChange={(e) => void pick(e)} {...{ webkitdirectory: '' }} />
                    </div>
                )}
                <div>
                    <p className={FIELD_LABEL}>Attach it to</p>
                    <AgentPicks value={agents} onChange={setAgents} />
                </div>
            </div>
        </ShellDialog>
    );
}

/** New memory: a name, the line agents see, and which agents read or write it. */
export function NewMemoryDialog({ agent, onClose, inline }: { agent?: string; onClose: (created?: Knowledge) => void; inline?: boolean }) {
    const client = useWorkClient();
    const k = useKnowledge();
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [agents, setAgents] = useState<string[]>(agent ? [agent] : []);
    const [writes, setWrites] = useState(true);
    const [busy, setBusy] = useState(false);
    const taken = k.memories.some((m) => m.name === name);
    const valid = /^[a-z0-9._-]{1,64}$/.test(name) && description.trim().length > 0 && !taken;
    const create = async () => {
        setBusy(true);
        try {
            const made = await createMemory(client, name, description.trim());
            invalidateV1(MEMORIES_KEY);
            const attached = await attachAll(client, k.agents.filter((a) => agents.includes(a.id)), made, writes);
            toast(`${made.name} is in Resources`, { description: attached.length ? `${list(attached)} ${writes ? 'read and write' : 'read'} it from the next conversation.` : undefined });
            onClose(made);
        } catch (error) {
            toast.error('Couldn’t make the memory', { description: error instanceof Error ? error.message : String(error) });
            setBusy(false);
        }
    };
    return (
        <ShellDialog
            open
            inline={inline}
            onOpenChange={(o) => !o && onClose()}
            title="New memory"
            description="Notes any agent you pick reads, and, where you let it, adds to as it learns."
            mark={<Brain className="h-5 w-5" strokeWidth={1.75} />}
            size="md"
            testId="new-memory"
            footer={
                <div className="flex justify-end gap-2">
                    <button type="button" onClick={() => onClose()} className={BUTTON_GHOST}>
                        Cancel
                    </button>
                    <button type="button" disabled={!valid || busy} onClick={() => void create()} className={BUTTON_PRIMARY}>
                        Create memory
                    </button>
                </div>
            }
        >
            <div className="flex flex-col gap-4">
                <label>
                    <span className={FIELD_LABEL}>Name</span>
                    <input value={name} onChange={(e) => setName(e.target.value.toLowerCase().replace(/[^a-z0-9._-]/g, '-'))} placeholder="customers" className={cn(PILL_FIELD, 'font-mono text-[13px]')} />
                    {taken && <span className="mt-1.5 block text-[12.5px] text-red-600 dark:text-red-400">There’s a memory called that already.</span>}
                </label>
                <label>
                    <span className={FIELD_LABEL}>What it holds</span>
                    <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Each customer: what they run and what they’ve asked for" className={PILL_FIELD} />
                </label>
                <div>
                    <p className={FIELD_LABEL}>Attach it to</p>
                    <AgentPicks value={agents} onChange={setAgents} refusal={(a) => memoryRefusal(a, { kind: 'memory', id: '', name, description, agentId: null, attachedTo: [], entryCount: 0, userId: null, createdAt: null, updatedAt: null })} />
                    <div className="mt-3">
                        <Toggle on={writes} onChange={setWrites} title="They can add to it" note="Each saves what it learns here, for the others to read. Off: they only read, and only people change it." />
                    </div>
                </div>
            </div>
        </ShellDialog>
    );
}
