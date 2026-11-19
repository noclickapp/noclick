// A skill's page under its head: the agents that use it (each following the latest or holding a version), the
// harnesses it runs on, its files (SKILL.md and the scripts it uses, editable as a new version), and its versions to
// restore. Saving a skill several agents use says who gets the change; "Make a copy" gives one agent its own.
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Check, ChevronDown, Copy, FileCode2, FileText, History, X } from 'lucide-react';
import { useWorkClient } from '../../client';
import { useWorkV1 } from '../../agents/reads';
import { HarnessMark, harnessLabel } from '../../agents/harness';
import { invalidateV1 } from '@/sdk/useV1';
import type { HarnessName } from 'noclick';
import {
    createSkill,
    readSkillFile,
    restoreSkill,
    saveSkill,
    setAgentLinks,
    skillVersions,
    type AgentRef,
    type Skill,
    type SkillVersion,
} from '@/screens/resources/knowledge';
import { BUTTON_GHOST } from '@/ui/buttons';
import { MENU_SURFACE } from '@/ui/menus';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/ui/dropdown-menu';
import { fmtBytes, relTime } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { AgentFace, AREA, Faces, list, PageSection, SMALL_PRIMARY, SMALL_SECONDARY, UsedByList, WriterFace, writerName, XS } from './parts';
import { readLinksAgain, SKILLS_KEY, useKnowledge, type Use } from './store';
import { setMode, useMode } from './mode';

const SKILL_MD = 'SKILL.md';

/** How each harness gets a skill: written where it looks at every cold start, or, for NoClick's agent, listed each turn. */
export const DELIVERY: { harness: HarnessName; how: string }[] = [
    { harness: 'claude_code', how: 'Finds it itself, as on your laptop' },
    { harness: 'codex', how: 'Finds it itself' },
    { harness: 'opencode', how: 'Its skill tool loads it' },
    { harness: 'hermes', how: 'Loads it from its skills folder' },
    { harness: 'openclaw', how: 'Loads it from its skills folder' },
    { harness: 'sdk', how: 'Reads it when it needs it; runs its scripts in its shell' },
];

/** Its scripts run on Node: a script NoClick's Hermes image can't run. */
const needsNode = (files: { path: string }[]) => files.some((f) => /\.(m?js|cjs|ts)$/.test(f.path) || f.path === 'package.json');

/** Whether a harness can follow it, and what to know when it can. */
export function runsOn(skill: Skill, files: { path: string }[], harness: HarnessName): { ok: boolean; note?: string } {
    if (needsNode(files) && harness === 'hermes') return { ok: false, note: 'Its script needs Node, which Hermes’s image hasn’t' };
    if (skill.always) return { ok: true, note: 'Added to its instructions every turn' };
    if (harness === 'sdk' && files.some((f) => f.path.startsWith('scripts/'))) return { ok: true, note: 'Its scripts need the shell, which starts when it’s used' };
    return { ok: true };
}

/** What a version changed from the one before it, in a line: "Changed SKILL.md", "Added scripts/collect.mjs and 1 more". */
export function versionNote(version: SkillVersion, before: SkillVersion | undefined): string {
    if (!before) return 'First version';
    const old = new Map(before.files.map((f) => [f.path, f]));
    const now = new Map(version.files.map((f) => [f.path, f]));
    const added = version.files.filter((f) => !old.has(f.path)).map((f) => f.path);
    const removed = before.files.filter((f) => !now.has(f.path)).map((f) => f.path);
    const changed = version.files.filter((f) => old.has(f.path) && (old.get(f.path)!.sha256 !== f.sha256 || old.get(f.path)!.size !== f.size)).map((f) => f.path);
    const say = (verb: string, paths: string[]) => (paths.length ? `${verb} ${paths[0]}${paths.length > 1 ? ` and ${paths.length - 1} more` : ''}` : null);
    return [say('Changed', changed), say('Added', added), say('Removed', removed)].filter(Boolean).join(', ') || 'Saved again, unchanged';
}

const versionsKey = (id: string) => `${SKILLS_KEY}/${id}/versions`;

export function useSkillVersions(skill: Skill) {
    // Keyed by its version, so a new one reads them again.
    return useWorkV1(`${versionsKey(skill.id)}@${skill.version}`, (client) => skillVersions(client, skill.id));
}

function useSkillFile(skill: Skill, path: string, version?: number) {
    return useWorkV1(`${SKILLS_KEY}/${skill.id}/files/${path}@${version ?? skill.version}`, (client) => readSkillFile(client, skill.id, path, version ?? skill.version));
}

export function SkillBody({ skill, from, onOpen, now }: { skill: Skill; from?: string; onOpen?: (id: string) => void; now: string }) {
    const client = useWorkClient();
    const k = useKnowledge();
    const users = k.usersOf(skill);
    const versions = useSkillVersions(skill).data ?? [];
    const latest = versions.find((v) => v.version === skill.version);
    const files = latest?.files ?? [{ path: SKILL_MD, size: skill.size }];
    const [file, setFile] = useState(SKILL_MD);
    const shown = useSkillFile(skill, file);
    const markdown = useSkillFile(skill, SKILL_MD);
    const editing = useMode(skill.id) === 'editing';
    const setEditing = (on: boolean) => setMode(skill.id, on ? 'editing' : null);
    const [draft, setDraft] = useState<string | null>(null);
    // Edit starts from SKILL.md as it is now, once it's read.
    useEffect(() => {
        if (!editing) setDraft(null);
        else if (draft === null && markdown.data) setDraft(markdown.data.content);
    }, [editing, draft, markdown.data]);
    useEffect(() => () => setMode(skill.id, null), [skill.id]);
    const [busy, setBusy] = useState(false);
    const notes = versions.map((v, i) => ({ version: v.version, note: versionNote(v, versions[i + 1]) }));
    const next = skill.version + 1;

    const save = async () => {
        setBusy(true);
        try {
            await saveSkill(client, skill.id, [{ path: SKILL_MD, content: draft ?? '' }], skill.version);
        } catch (error) {
            toast.error('Couldn’t save it', { description: error instanceof Error ? error.message : String(error) });
            setBusy(false);
            return;
        }
        setBusy(false);
        setEditing(false);
        invalidateV1(SKILLS_KEY);
        const following = users.filter((u) => !u.link?.pin);
        toast(`${skill.name} v${next} saved`, {
            description: following.length
                ? `${list(following.map((u) => u.agent.name))} ${following.length === 1 ? 'gets' : 'get'} it from the next conversation.`
                : 'No agent follows the latest, so nothing changes yet.',
        });
    };

    const copyFor = async (agent: AgentRef) => {
        const name = `${skill.name}-${agent.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}`.slice(0, 64);
        setBusy(true);
        try {
            const others = await Promise.all(files.filter((f) => f.path !== SKILL_MD).map((f) => readSkillFile(client, skill.id, f.path, skill.version)));
            const made = await createSkill(client, [{ path: SKILL_MD, content: (draft ?? '').replace(/^name:.*$/m, `name: ${name}`) }, ...others]);
            await setAgentLinks(client, agent, { skills: agent.skills.map((s) => (s.id === skill.id ? { id: made.id, pin: null } : s)) });
            readLinksAgain();
            setEditing(false);
            toast(`${agent.name} now has its own copy`, { description: `${name} is ${agent.name}’s alone; the others keep ${skill.name} as it was.` });
            onOpen?.(made.id);
        } catch (error) {
            toast.error('Couldn’t make the copy', { description: error instanceof Error ? error.message : String(error) });
        } finally {
            setBusy(false);
        }
    };

    const restore = async (v: SkillVersion) => {
        try {
            await restoreSkill(client, skill.id, v.version);
            invalidateV1(SKILLS_KEY);
            toast(`Restored v${v.version} as v${skill.version + 1}`);
        } catch (error) {
            toast.error('Couldn’t restore it', { description: error instanceof Error ? error.message : String(error) });
        }
    };

    if (editing) {
        return (
            <section className="mt-6" data-testid="skill-edit">
                <SharedEditNotice users={users} />
                <textarea aria-label="SKILL.md" value={draft ?? ''} onChange={(e) => setDraft(e.target.value)} rows={14} spellCheck={false} className={cn(AREA, 'mt-4 font-mono text-[12.5px]')} />
                <div className="mt-3 flex flex-wrap items-center gap-2">
                    <button type="button" onClick={() => void save()} disabled={busy || draft === null || draft === markdown.data?.content} className={SMALL_PRIMARY}>
                        Save as v{next}
                    </button>
                    {users.length > 1 && <CopyForMenu users={users.map((u) => u.agent)} from={from} onPick={(a) => void copyFor(a)} disabled={busy} />}
                    <button type="button" onClick={() => setEditing(false)} className={BUTTON_GHOST.replace('h-9', 'h-8')}>
                        Cancel
                    </button>
                </div>
            </section>
        );
    }

    return (
        <div data-testid="skill-body">
            <PageSection title="Used by" meta={users.length}>
                <UsedByList item={skill} versions={notes} />
            </PageSection>
            <PageSection title="Runs on">
                {skill.always ? (
                    <>
                        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                            {DELIVERY.map((d) => (
                                <span key={d.harness} className="inline-flex items-center gap-1.5 text-sm">
                                    <HarnessMark harness={d.harness} className="h-4 w-4" />
                                    {harnessLabel(d.harness)}
                                    <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" strokeWidth={2.5} />
                                </span>
                            ))}
                        </div>
                        <p className="mt-2 text-xs text-muted-foreground">In every turn: it joins the instructions, so every harness follows it the way it follows its own.</p>
                    </>
                ) : (
                    <ul className="grid gap-x-6 gap-y-1 sm:grid-cols-2" data-testid="runs-on">
                        {DELIVERY.map((d) => {
                            const r = runsOn(skill, files, d.harness);
                            return (
                                <li key={d.harness} className="flex items-start gap-2.5 py-1.5">
                                    <HarnessMark harness={d.harness} className="mt-0.5 h-4 w-4" />
                                    <span className="min-w-0 flex-1">
                                        <span className="flex items-center gap-1.5 text-sm">
                                            {harnessLabel(d.harness)}
                                            {r.ok ? (
                                                <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" strokeWidth={2.5} />
                                            ) : (
                                                <X className="h-3.5 w-3.5 text-red-600 dark:text-red-400" strokeWidth={2.5} />
                                            )}
                                        </span>
                                        <span className={cn('block text-xs', r.ok ? 'text-muted-foreground' : 'text-red-600 dark:text-red-400')}>{r.note ?? d.how}</span>
                                    </span>
                                </li>
                            );
                        })}
                    </ul>
                )}
            </PageSection>
            <PageSection title="Files" meta={files.length}>
                <div className="flex flex-col gap-3 lg:flex-row">
                    <ul className="flex shrink-0 gap-1 overflow-x-auto lg:w-[210px] lg:flex-col" aria-label="Files">
                        {files.map((f) => (
                            <li key={f.path}>
                                <button
                                    type="button"
                                    onClick={() => setFile(f.path)}
                                    className={cn(
                                        'flex w-full items-center gap-2 rounded-full px-3 py-1.5 text-left text-[13px] transition-colors',
                                        file === f.path ? 'bg-foreground/[0.08] text-foreground' : 'text-muted-foreground hover:bg-foreground/[0.04] hover:text-foreground'
                                    )}
                                >
                                    {f.path.endsWith('.md') ? <FileText className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} /> : <FileCode2 className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />}
                                    <span className="truncate font-mono text-[12px]">{f.path}</span>
                                    <span className="ml-auto shrink-0 pl-2 text-[11px] tabular-nums text-muted-foreground">{fmtBytes(f.size)}</span>
                                </button>
                            </li>
                        ))}
                    </ul>
                    <pre className="min-w-0 flex-1 overflow-x-auto whitespace-pre-wrap rounded-xl bg-foreground/[0.04] p-4 font-mono text-[12.5px] leading-relaxed text-foreground/90" data-testid="skill-file">
                        {shown.data ? (shown.data.encoding === 'base64' ? 'This file isn’t text.' : shown.data.content) : shown.error ? 'It couldn’t be read.' : ' '}
                    </pre>
                </div>
            </PageSection>
            <PageSection title="Versions" meta={versions.length || undefined}>
                <ul className="-mx-2.5">
                    {versions.map((v, i) => {
                        const held = users.filter((u) => u.link?.pin === v.version).map((u) => u.agent.name);
                        return (
                            <li key={v.version} className="flex items-center gap-3 rounded-xl px-2.5 py-2">
                                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-foreground/[0.06] text-[11px] font-semibold tabular-nums text-foreground/70">v{v.version}</span>
                                <div className="min-w-0 flex-1">
                                    <p className="truncate text-sm">{notes[i].note}</p>
                                    <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                                        <WriterFace who={v.createdBy} />
                                        {writerName(v.createdBy)}
                                        {v.createdAt ? ` · ${relTime(v.createdAt, now)}` : ''}
                                        {v.version === skill.version && ' · Latest'}
                                        {held.length > 0 && ` · ${list(held)} ${held.length === 1 ? 'holds' : 'hold'} this one`}
                                    </p>
                                </div>
                                {v.version !== skill.version && (
                                    <button type="button" onClick={() => void restore(v)} className={cn(XS, 'text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground')}>
                                        <History className="h-3.5 w-3.5" strokeWidth={1.75} />
                                        Restore
                                    </button>
                                )}
                            </li>
                        );
                    })}
                </ul>
            </PageSection>
        </div>
    );
}

/** What saving a skill several agents use does: the ones following the latest get it, the held ones don't. */
function SharedEditNotice({ users }: { users: Use[] }) {
    if (!users.length) return <p className="text-sm text-muted-foreground">No agent uses it yet, so saving changes nothing anyone runs.</p>;
    const latest = users.filter((u) => !u.link?.pin).map((u) => u.agent);
    const held = users.filter((u) => u.link?.pin);
    return (
        <div className="rounded-xl bg-foreground/[0.05] px-4 py-3.5" data-testid="shared-edit-notice">
            <div className="flex items-center gap-2.5">
                <Faces agents={users.map((u) => u.agent)} size={24} />
                <p className="text-sm font-medium">
                    Used by {users.length} {users.length === 1 ? 'agent' : 'agents'}
                </p>
            </div>
            <ul className="mt-2 space-y-1 text-[13px] leading-snug text-foreground/85">
                {latest.length > 0 && (
                    <li>
                        {list(latest.map((a) => a.name))} {latest.length === 1 ? 'follows' : 'follow'} the latest: your change reaches {latest.length === 1 ? 'it' : 'them'} from the next conversation, and a
                        sandbox that’s running restarts to pick it up.
                    </li>
                )}
                {held.map((u) => (
                    <li key={u.agent.id}>
                        {u.agent.name} holds v{u.link!.pin} and keeps it.
                    </li>
                ))}
                {users.length > 1 && <li className="text-muted-foreground">For one agent only, make it a copy: that agent gets its own skill, and the others keep this one.</li>}
            </ul>
        </div>
    );
}

function CopyForMenu({ users, from, onPick, disabled }: { users: AgentRef[]; from?: string; onPick: (agent: AgentRef) => void; disabled?: boolean }) {
    const first = users.find((a) => a.id === from) ?? users[0];
    return (
        <span className="inline-flex">
            <button type="button" disabled={disabled} onClick={() => onPick(first)} className={cn(SMALL_SECONDARY, 'rounded-r-none pr-2.5')}>
                <Copy className="h-3.5 w-3.5" strokeWidth={2} />
                Make a copy for {first.name}
            </button>
            <DropdownMenu>
                <DropdownMenuTrigger aria-label="Copy for another agent" disabled={disabled} className={cn(SMALL_SECONDARY, 'rounded-l-none border-l border-background/60 px-2 dark:border-background/40')}>
                    <ChevronDown className="h-3.5 w-3.5" strokeWidth={2} />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" sideOffset={6} className={cn('w-[220px] rounded-xl p-1', MENU_SURFACE)}>
                    {users.map((a) => (
                        <DropdownMenuItem key={a.id} onSelect={() => onPick(a)} className="gap-2.5 rounded-lg px-2.5 py-2 text-[14px]">
                            <AgentFace agent={a} size={20} />
                            For {a.name}
                        </DropdownMenuItem>
                    ))}
                </DropdownMenuContent>
            </DropdownMenu>
        </span>
    );
}
