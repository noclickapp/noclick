// Policy: which tools may run, per layer (the account, or one user layered
// after it). Three editable pattern lists, a preview that judges a tool name
// against the unsaved draft, the tools whose verdict the draft would change,
// and a save that confirms its diff. `?layer=<user id>`; absent is the account.
// Rules with a condition or an approver are set from code: they're shown in
// their list and kept on save, never edited here; the preview judges them on
// the arguments it's given.
import { useEffect, useState, type KeyboardEvent } from 'react';
import { ChevronDown, X } from 'lucide-react';
import { Link } from 'react-router';
import { toast } from 'sonner';
import { Popover, PopoverContent, PopoverTrigger } from '@/ui/popover';
import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { Agent, ALL_USERS, Connection, HumanRequest, Policy, Rule, type JsonObject, type PolicyVerdict } from 'noclick';
import { BUCKET_TOOLS } from '@/sdk/source';
import { refFor } from '@/lib/agentTools';
import { snippetTabs, POLICY_EMPTY, POLICY_RULE } from '@/screens/console/lib/snippets';
import type { StatusLook } from '@/screens/console/lib/status';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { ConsoleButton } from '../ui/Button';
import { CodeSnippet } from '../ui/CodeSnippet';
import { ConsoleDialog } from '../ui/ConsoleDialog';
import { ErrorPanel } from '../ui/ErrorPanel';
import { PageHeader } from '../ui/PageHeader';
import { StatusPill } from '../ui/StatusPill';
import { UserPickerList } from '../ui/UserFacet';
import { accountFreeIntegration, accountFreeOperations, agentsToolsOf, bucketRefOf, catalogOperations, databaseRefOf, entryRef, personToolOf, sharedConnectionOf } from '../agentParts';

/** `policy/service.MAX_PATTERNS` and `_PATTERN_RE`. */
export const MAX_PATTERNS = 200;
const PATTERN_RE = /^[a-z0-9_*-]+(\.[a-z0-9_*-]+)*$/;
/** `POST /v1/policy/evaluate` takes at most this many tools. */
export const MAX_EVALUATE_TOOLS = 500;
/** Agent tool refs that are capabilities, not integrations (`agents/compiler.AGENT_CAPABILITIES`). */
const AGENT_CAPABILITIES = new Set(['search', 'fetch', 'code']);

export type ListName = 'deny' | 'allow' | 'requireApproval';

/** A rule with a condition or an approver, as its list holds it. */
export interface ConditionRule {
    rule: Rule;
    /** Who approves its held calls, as the approval page names them (null: the owner of what the call acts in). */
    approver: string | null;
}

/** A list entry: a pattern, which this page edits, or a rule set from code, which it keeps. */
export type RuleEntry = string | ConditionRule;

export interface Rules {
    allow: RuleEntry[];
    deny: RuleEntry[];
    requireApproval: RuleEntry[];
}

const WIRE_LIST: Record<ListName, 'allow' | 'deny' | 'require_approval'> = { allow: 'allow', deny: 'deny', requireApproval: 'require_approval' };

/** Who a rule's `approver` (`{email}`, `{user_id}` or `{user: true}` on the wire) names. */
export function approverLabel(approver: unknown): string | null {
    if (!approver || typeof approver !== 'object') return typeof approver === 'string' ? approver : null;
    const a = approver as JsonObject;
    if (typeof a.email === 'string') return a.email;
    if (typeof a.user_id === 'string') return a.user_id;
    return a.user ? 'the user the call is for' : null;
}

/** `stripe.create_refund when args.amount > 10000, approved by finance@acme.com` */
export function entryText(entry: RuleEntry): string {
    if (typeof entry === 'string') return entry;
    const { rule, approver } = entry;
    return `${rule.tool}${rule.when ? ` when ${rule.when}` : ''}${approver ? `, approved by ${approver}` : ''}`;
}

const entryKey = (entry: RuleEntry) => (typeof entry === 'string' ? entry : `${entryText(entry)}\u0000rule`);
const toWire = (entry: RuleEntry): string | Rule => (typeof entry === 'string' ? entry : entry.rule);

const LISTS: readonly { name: ListName; label: string; word: string; hint: string }[] = [
    { name: 'deny', label: 'Deny', word: 'deny', hint: 'Never run. A deny in any layer wins.' },
    { name: 'allow', label: 'Allow', word: 'allow', hint: 'Only these run. Empty allows every tool.' },
    { name: 'requireApproval', label: 'Require approval', word: 'require approval', hint: 'Run once a person approves the call.' },
];

/** A pattern as the API stores it, or the reason it isn't one. */
export function checkPattern(raw: string): { pattern: string } | { error: string } {
    const pattern = raw.trim().toLowerCase();
    if (!pattern) return { error: 'Type a tool name or pattern.' };
    if (pattern.length > 200 || !PATTERN_RE.test(pattern)) {
        return { error: `'${raw.trim()}' isn't a tool pattern. Use dotted names with * wildcards: gmail.*, *.delete_*, search.` };
    }
    return { pattern };
}

/** `gmail__send_email` → `gmail.send_email` (`policy/service.normalize_tool_name`). */
export function normalizeToolName(name: string): string {
    const lower = name.trim().toLowerCase();
    const at = lower.indexOf('__');
    return at < 0 ? lower : `${lower.slice(0, at)}.${lower.slice(at + 2)}`;
}

/** "+ deny `*.delete_*`" lines, in list order. */
export function ruleDiff(saved: Rules, draft: Rules): string[] {
    const out: string[] = [];
    for (const { name, word } of LISTS) {
        const had = new Set(saved[name].map(entryKey));
        const has = new Set(draft[name].map(entryKey));
        for (const p of draft[name]) if (!had.has(entryKey(p))) out.push(`+ ${word} \`${entryText(p)}\``);
        for (const p of saved[name]) if (!has.has(entryKey(p))) out.push(`− ${word} \`${entryText(p)}\``);
    }
    return out;
}

const sameRules = (a: Rules, b: Rules) => LISTS.every(({ name }) => a[name].map(entryKey).join('\n') === b[name].map(entryKey).join('\n'));

export function policyVerdictLook(verdict: PolicyVerdict['verdict']): StatusLook {
    if (verdict === 'deny') return { label: 'Denied', glyph: 'cross', tone: 'failure' };
    if (verdict === 'approval') return { label: 'Needs approval', glyph: 'waiting', tone: 'ink' };
    return { label: 'Allowed', glyph: 'check', tone: 'ink' };
}

function matchedBy(v: PolicyVerdict): string {
    if (v.rule instanceof Rule && (v.rule.when || v.rule.approver)) {
        const row = v.raw.rule && typeof v.raw.rule === 'object' ? (v.raw.rule as JsonObject) : {};
        return `${v.layer} rule ${entryText({ rule: v.rule, approver: approverLabel(row.approver) })}`;
    }
    if (v.matchedPattern) return `${v.layer} rule ${v.matchedPattern}`;
    if (v.verdict === 'deny') return `not in the ${v.layer} allow list`;
    return 'no rule matches';
}

function useDebounced<T>(value: T, ms: number): T {
    const [out, setOut] = useState(value);
    useEffect(() => {
        const t = window.setTimeout(() => setOut(value), ms);
        return () => window.clearTimeout(t);
    }, [value, ms]);
    return out;
}

function PatternList({ label, hint, entries, onChange }: { label: string; hint: string; entries: RuleEntry[]; onChange: (next: RuleEntry[]) => void }) {
    const [draft, setDraft] = useState('');
    const [error, setError] = useState<string | null>(null);
    const patterns = entries.filter((e): e is string => typeof e === 'string');
    const rules = entries.filter((e): e is ConditionRule => typeof e !== 'string');
    const full = entries.length >= MAX_PATTERNS;
    const add = () => {
        if (!draft.trim()) return;
        const checked = checkPattern(draft);
        if ('error' in checked) return setError(checked.error);
        if (full) return setError(`A list holds at most ${MAX_PATTERNS} patterns.`);
        setError(null);
        setDraft('');
        if (!patterns.includes(checked.pattern)) onChange([...entries, checked.pattern]);
    };
    const lastPattern = patterns[patterns.length - 1];
    const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault();
            add();
        } else if (e.key === 'Backspace' && !draft && lastPattern !== undefined) {
            onChange(entries.filter((x) => x !== lastPattern));
        }
    };
    return (
        <section className={cn('border-t pt-4', HAIRLINE)}>
            <div className="mb-2 flex items-baseline justify-between gap-3">
                <h2 className="m-0 text-[13px] font-semibold text-foreground">{label}</h2>
                <span className="text-[12px] tabular-nums text-muted-foreground">
                    {entries.length} of {MAX_PATTERNS}
                </span>
            </div>
            <p className="m-0 mb-2.5 text-[12px] text-muted-foreground">{hint}</p>
            <div className="flex min-h-9 flex-wrap items-center gap-1 rounded-lg border border-input bg-background px-2 py-1 focus-within:ring-2 focus-within:ring-ring">
                {patterns.map((p) => (
                    <span key={p} className="inline-flex items-center gap-0.5 rounded bg-foreground/[0.06] px-1.5 py-[1px] font-mono text-[12px] text-foreground">
                        {p}
                        <button type="button" aria-label={`Remove ${p} from ${label}`} onClick={() => onChange(entries.filter((x) => x !== p))} className="rounded text-muted-foreground hover:text-foreground">
                            <X className="h-3 w-3" />
                        </button>
                    </span>
                ))}
                <input
                    value={draft}
                    aria-label={`Add to ${label}`}
                    placeholder={patterns.length ? '' : 'gmail.*'}
                    onChange={(e) => {
                        setDraft(e.target.value);
                        setError(null);
                    }}
                    onKeyDown={onKeyDown}
                    onBlur={add}
                    disabled={full}
                    className="h-7 min-w-[8rem] flex-1 bg-transparent font-mono text-[12px] text-foreground outline-none placeholder:text-[hsl(var(--placeholder))]"
                />
            </div>
            {error && (
                <p role="alert" className="m-0 mt-1.5 text-[12px] text-red-600 dark:text-red-400">
                    {error}
                </p>
            )}
            {rules.length > 0 && (
                <ul aria-label={`${label}: rules with conditions`} className={cn('m-0 mt-2.5 flex list-none flex-col border-t p-0', HAIRLINE)}>
                    {rules.map((r) => (
                        <li key={entryKey(r)} className={cn('flex items-start justify-between gap-2 py-1.5')}>
                            <span className="flex min-w-0 flex-col gap-0.5">
                                <span className="truncate font-mono text-[12px] text-foreground">{r.rule.tool}</span>
                                {r.rule.when && <span className="break-words font-mono text-[12px] text-muted-foreground">when {r.rule.when}</span>}
                                {r.approver && <span className="text-[12px] text-muted-foreground">Approved by {r.approver}</span>}
                            </span>
                            <button type="button" aria-label={`Remove the ${r.rule.tool} rule from ${label}`} onClick={() => onChange(entries.filter((x) => x !== r))} className="mt-0.5 rounded text-muted-foreground hover:text-foreground">
                                <X className="h-3 w-3" />
                            </button>
                        </li>
                    ))}
                </ul>
            )}
        </section>
    );
}

function draftBody(layer: 'account' | 'user', rules: Rules) {
    return { layer, allow: rules.allow.map(toWire), deny: rules.deny.map(toWire), requireApproval: rules.requireApproval.map(toWire) };
}

/** `{"amount": 25000}` → the object, or why it isn't one. */
export function parseArguments(text: string): { args: JsonObject | undefined } | { error: string } {
    if (!text.trim()) return { args: undefined };
    try {
        const parsed: unknown = JSON.parse(text);
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return { args: parsed as JsonObject };
    } catch {
        // Reported below, like a value that isn't an object.
    }
    return { error: 'Arguments are a JSON object, like {"amount": 25000}.' };
}

function Preview({ user, draft }: { user: string | null; draft: Rules }) {
    const { client } = useConsole();
    const [tool, setTool] = useState('');
    const [argsText, setArgsText] = useState('');
    const name = useDebounced(normalizeToolName(tool), 250);
    const argsRaw = useDebounced(argsText, 250);
    // A rule's `when` reads the call's arguments; without them such a rule never matches.
    const parsed = parseArguments(argsRaw);
    const args = 'args' in parsed ? parsed.args : undefined;
    const layer = user ? 'user' : 'account';
    const result = useV1(name && !('error' in parsed) ? `policy/evaluate?preview&${user}&${name}&${JSON.stringify(args ?? null)}&${JSON.stringify(draftBody(layer, draft))}` : null, () =>
        Policy.evaluate([name], { client, user, draft: draftBody(layer, draft), arguments: args })
    );
    const verdict = result.data?.[0];
    return (
        <section className={cn('border-t pt-4', HAIRLINE)}>
            <h2 className="m-0 mb-2 text-[13px] font-semibold text-foreground">Preview</h2>
            <input
                value={tool}
                onChange={(e) => setTool(e.target.value)}
                aria-label="Tool to judge"
                placeholder="gmail.send_email"
                className="h-9 w-full rounded-md border border-input bg-background px-3 font-mono text-[12px] text-foreground outline-none placeholder:text-[hsl(var(--placeholder))] focus-visible:ring-2 focus-visible:ring-ring"
            />
            <input
                value={argsText}
                onChange={(e) => setArgsText(e.target.value)}
                aria-label="Arguments to judge"
                placeholder='Arguments, for rules with conditions: {"amount": 25000}'
                className="mt-2 h-9 w-full rounded-md border border-input bg-background px-3 font-mono text-[12px] text-foreground outline-none placeholder:text-[hsl(var(--placeholder))] focus-visible:ring-2 focus-visible:ring-ring"
            />
            <div className="mt-2.5 min-h-7 text-[13px]" aria-live="polite">
                {'error' in parsed ? (
                    <span role="alert" className="text-[12px] text-red-600 dark:text-red-400">
                        {parsed.error}
                    </span>
                ) : result.error !== undefined ? (
                    <ErrorPanel error={result.error} className="border-0 bg-transparent p-0" />
                ) : verdict ? (
                    <span className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-[12px]">{verdict.tool}</span>
                        <StatusPill look={policyVerdictLook(verdict.verdict)} />
                        <span className="text-muted-foreground">{matchedBy(verdict)}</span>
                    </span>
                ) : (
                    <span className="text-muted-foreground">Judged against the rules as drafted, before you save.</span>
                )}
            </div>
        </section>
    );
}

/**
 * Every tool the account's agents can reach: capabilities, the operations of each connection they
 * name (by name in the agent's own scope, `credential:<id>` for an account connected in the app, or
 * `connection:<id>` from another), and, for a name with no connection, its integration's operations
 * that need no account, each under its integration.
 */
function useAgentTools() {
    const { client } = useConsole();
    return useV1('policy/agent-tools', async () => {
        const [agents, connections] = await Promise.all([Agent.list({ client, userFilter: ALL_USERS, limit: 200 }), Connection.list({ client, userFilter: ALL_USERS })]);
        const byRef = new Map(connections.map((c) => [`${c.userId ?? ''}/${refFor(c)}`, c]));
        const byId = new Map(connections.map((c) => [c.id, c]));
        const capabilities = new Set<string>();
        // Integrations reached through a connection, whole; and refs that name no connection.
        const whole = new Set<string>();
        const unnamed: { name: string; op: string | null }[] = [];
        for (const agent of agents) {
            for (const entry of agent.tools) {
                // A person's tools and a bucket's operations have policy names of their own.
                const person = personToolOf(entry);
                if (person) {
                    for (const tool of person.tools) capabilities.add(`human.${tool}`);
                    continue;
                }
                const ref = entryRef(entry);
                if (ref === null) continue;
                const bucket = bucketRefOf(ref);
                if (bucket) {
                    for (const op of bucket.op ? [bucket.op] : BUCKET_TOOLS) capabilities.add(`bucket.${op}`);
                    continue;
                }
                if (AGENT_CAPABILITIES.has(ref)) {
                    capabilities.add(ref);
                    continue;
                }
                const coordination = agentsToolsOf(ref);
                if (coordination) {
                    for (const tool of coordination) capabilities.add(`agents.${tool}`);
                    continue;
                }
                if (databaseRefOf(ref)) continue;
                const shared = sharedConnectionOf(ref);
                const [name, op] = ref.split('.');
                const connection = shared ? byId.get(shared.id) : byRef.get(`${agent.userId ?? ''}/${name}`);
                if (connection) whole.add(connection.integration ?? '');
                else if (!shared) unnamed.push({ name, op: op ?? null });
            }
        }
        const catalog = unnamed.length ? await Connection.integrations(undefined, { client }) : [];
        const free = unnamed.filter((u) => accountFreeIntegration(u.name, catalog));
        // Operations belong to the integration, so one read serves every ref to it.
        const read = [...new Set([...whole, ...free.map((u) => u.name)])];
        const operations = new Map(await Promise.all(read.map(async (name) => [name, await catalogOperations(name, client)] as const)));
        const opsOf = (name: string) =>
            whole.has(name)
                ? operations.get(name)!.map((o) => o.name)
                : [...new Set(free.filter((u) => u.name === name).flatMap((u) => accountFreeOperations(operations.get(name)!, u.op)))];
        const tools = [...capabilities, ...read.flatMap((name) => opsOf(name).map((op) => `${name}.${op}`))];
        return { tools: tools.slice(0, MAX_EVALUATE_TOOLS), truncated: tools.length > MAX_EVALUATE_TOOLS };
    });
}

function ToolsAffected({ user, draft, dirty }: { user: string | null; draft: Rules; dirty: boolean }) {
    const { client } = useConsole();
    const candidates = useAgentTools();
    const tools = candidates.data?.tools ?? [];
    const layer = user ? 'user' : 'account';
    const changes = useV1(dirty && tools.length ? `policy/evaluate?affected&${user}&${JSON.stringify(draft)}&${tools.length}` : null, async () => {
        const [before, after] = await Promise.all([
            Policy.evaluate(tools, { client, user }),
            Policy.evaluate(tools, { client, user, draft: draftBody(layer, draft) }),
        ]);
        return after.map((v, i) => ({ after: v, before: before[i] })).filter((c) => c.after.verdict !== c.before.verdict);
    });
    return (
        <section className={cn('border-t pt-4', HAIRLINE)}>
            <h2 className="m-0 mb-1 text-[13px] font-semibold text-foreground">Tools affected</h2>
            <p className="m-0 mb-2.5 text-[12px] text-muted-foreground">
                {`Your agents' tools whose verdict this draft changes${candidates.data?.truncated ? ` (the first ${MAX_EVALUATE_TOOLS})` : ''}.`}
            </p>
            {candidates.error !== undefined || changes.error !== undefined ? (
                <ErrorPanel error={candidates.error ?? changes.error} className="border-0 bg-transparent p-0" />
            ) : !dirty ? (
                <p className="m-0 text-[13px] text-muted-foreground">Edit a list to see what changes.</p>
            ) : candidates.loading || changes.loading ? (
                <div aria-busy className="h-16 animate-pulse rounded-lg bg-foreground/[0.04]" />
            ) : !tools.length ? (
                <p className="m-0 text-[13px] text-muted-foreground">Your agents have no integration tools yet.</p>
            ) : changes.data?.length ? (
                <ul aria-label="Tools affected" className="m-0 flex list-none flex-col p-0">
                    {changes.data.map(({ before, after }) => (
                        <li key={after.tool} className={cn('flex flex-wrap items-center gap-2 py-1.5')}>
                            <span className="min-w-0 flex-1 truncate font-mono text-[12px]">{after.tool}</span>
                            <StatusPill look={policyVerdictLook(before.verdict)} className="opacity-60" />
                            <span aria-hidden className="text-muted-foreground">→</span>
                            <StatusPill look={policyVerdictLook(after.verdict)} />
                        </li>
                    ))}
                </ul>
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">No agent tool changes verdict.</p>
            )}
        </section>
    );
}

/** The saved lists, each rule paired with its wire row for the approver it names. */
function fromPolicy(p: Policy): Rules {
    const entries = (name: ListName): RuleEntry[] => {
        const rows = Array.isArray(p.raw[WIRE_LIST[name]]) ? (p.raw[WIRE_LIST[name]] as unknown[]) : [];
        return p[name].map((entry, i) => {
            if (typeof entry === 'string') return entry;
            const row = rows[i];
            return { rule: entry, approver: approverLabel(row && typeof row === 'object' ? (row as JsonObject).approver : entry.approver) };
        });
    };
    return { allow: entries('allow'), deny: entries('deny'), requireApproval: entries('requireApproval') };
}

function Editor({ user, saved, label }: { user: string | null; saved: Rules; label: string }) {
    const { client } = useConsole();
    const [draft, setDraft] = useState<Rules>(saved);
    const [confirming, setConfirming] = useState(false);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const dirty = !sameRules(saved, draft);
    const diff = ruleDiff(saved, draft);
    const empty = LISTS.every(({ name }) => !saved[name].length);
    const save = async () => {
        setSaving(true);
        setError(undefined);
        try {
            await Policy.set({ allow: draft.allow.map(toWire), deny: draft.deny.map(toWire), requireApproval: draft.requireApproval.map(toWire) }, { client, user });
            setConfirming(false);
            // The saved rules and the layer list; agents' tools didn't change.
            invalidateV1('policy?');
            invalidateV1('policy/layers');
            toast(user ? `Saved ${label}'s policy` : 'Saved the account policy');
        } catch (e) {
            setError(e);
        } finally {
            setSaving(false);
        }
    };
    return (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,24rem)]">
            <div className="flex min-w-0 flex-col gap-5">
                {empty && !user && (
                    <div className={cn('border-t pt-4', HAIRLINE)}>
                        <p className="m-0 mb-2 text-[13px] text-foreground">No rules yet: every tool runs without asking. Set them here, or from code:</p>
                        <CodeSnippet tabs={snippetTabs(POLICY_EMPTY)} />
                    </div>
                )}
                {LISTS.map(({ name, label: listLabel, hint }) => (
                    <PatternList key={name} label={listLabel} hint={hint} entries={draft[name]} onChange={(next) => setDraft((d) => ({ ...d, [name]: next }))} />
                ))}
                <div className={cn('border-t pt-4', HAIRLINE)}>
                    <h2 className="m-0 mb-1 text-[13px] font-semibold text-foreground">Rules with conditions</h2>
                    <p className="m-0 mb-2.5 text-[12px] text-muted-foreground">
                        A rule can hold a call only when its arguments say so, and name who approves it. Set one from code; it shows in its list here, and saving here keeps it.
                    </p>
                    <CodeSnippet tabs={snippetTabs(POLICY_RULE)} />
                </div>
                <div className="flex items-center gap-2">
                    <ConsoleButton variant="primary" disabled={!dirty} onClick={() => setConfirming(true)}>
                        Save
                    </ConsoleButton>
                    <ConsoleButton variant="ghost" disabled={!dirty} onClick={() => setDraft(saved)}>
                        Discard changes
                    </ConsoleButton>
                </div>
            </div>
            <div className="flex min-w-0 flex-col gap-5">
                <Preview user={user} draft={draft} />
                <ToolsAffected user={user} draft={draft} dirty={dirty} />
            </div>
            <ConsoleDialog
                open={confirming}
                onOpenChange={setConfirming}
                title={user ? `Save ${label}'s policy?` : 'Save the account policy?'}
                description="It applies to the next call; calls already waiting on an approval keep it."
                footer={
                    <>
                        <ConsoleButton variant="ghost" onClick={() => setConfirming(false)}>
                            Cancel
                        </ConsoleButton>
                        <ConsoleButton variant="primary" disabled={saving} onClick={() => void save()}>
                            {saving ? 'Saving…' : 'Save policy'}
                        </ConsoleButton>
                    </>
                }
            >
                <ul aria-label="Changes" className="m-0 flex list-none flex-col gap-1 p-0 font-mono text-[12px]">
                    {diff.map((line) => (
                        <li key={line} className={line.startsWith('−') ? 'text-muted-foreground' : 'text-foreground'}>
                            {line.replace(/`/g, '')}
                        </li>
                    ))}
                </ul>
                {error !== undefined && <ErrorPanel error={error} className="mt-3" />}
            </ConsoleDialog>
        </div>
    );
}

/** One layer's rules: the account's (`user` null) or a user's. */
export function PolicyEditor({ user, label }: { user: string | null; label: string }) {
    const { client } = useConsole();
    const saved = useV1(user ? `policy?user=${user}` : 'policy?account', () => Policy.get({ client, user }));
    if (saved.error !== undefined && !saved.data) return <ErrorPanel error={saved.error} onRetry={() => void saved.refresh()} />;
    if (!saved.data) return <div aria-busy className="h-72 animate-pulse rounded-xl bg-foreground/[0.04]" />;
    const rules = fromPolicy(saved.data);
    return <Editor key={`${user}:${String(saved.data.raw.updated_at)}`} user={user} saved={rules} label={label} />;
}

function LayerPicker({ user, label, onChange }: { user: string | null; label: string; onChange: (user: string | null) => void }) {
    const { client } = useConsole();
    const [open, setOpen] = useState(false);
    const layers = useV1('policy/layers', () => Policy.list({ client }));
    const withRules = (layers.data ?? []).filter((p) => p.userId);
    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger className="inline-flex h-8 max-w-[18rem] items-center gap-1 rounded-md bg-foreground/[0.05] px-2.5 text-[13px] text-muted-foreground transition-colors hover:bg-foreground/[0.08] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                Layer: <span className={cn('truncate font-medium text-foreground')}>{label}</span>
                <ChevronDown className="h-3.5 w-3.5 shrink-0" />
            </PopoverTrigger>
            <PopoverContent align="end" className="w-72 p-1.5">
                {open && (
                    <UserPickerList
                        selected={user}
                        fixed={[
                            { value: null, label: 'Account (every call)' },
                            ...withRules.map((p) => ({ value: p.userId, label: `${p.userId} · has rules` })),
                        ]}
                        onPick={(v) => {
                            onChange(v);
                            setOpen(false);
                        }}
                    />
                )}
            </PopoverContent>
        </Popover>
    );
}

function usePendingApprovals() {
    const { client } = useConsole();
    return useV1('humans/requests?policy-approvals', async () => {
        const page = await HumanRequest.listPage({ client, kind: 'approve', status: 'pending', userFilter: ALL_USERS, limit: 100 });
        const count = page.data.filter((r) => r.request.approval).length;
        return { count, more: page.nextCursor !== null };
    });
}

export default function PolicyPage() {
    // `?layer=` names the user whose rules these are; absent, the account's.
    const [layer, setLayer] = useSearchParam('layer');
    const user = layer || null;
    const href = useConsoleHref();
    const pending = usePendingApprovals();
    const label = user ?? 'Account';
    const count = pending.data?.count ?? 0;
    return (
        <>
            <PageHeader
                crumbs={[{ label: 'Settings', href: href('settings') }]}
                title="Approval rules"
                purpose="Which tools need a person to approve each call, and which never run."
                actions={
                    <>
                        {pending.error !== undefined && <span className="text-[12px] text-muted-foreground">{"Couldn't count pending approvals."}</span>}
                        {count > 0 && (
                            <Link to={href('')} className="text-[13px] text-foreground hover:underline">
                                {count}
                                {pending.data?.more ? '+' : ''} {count === 1 ? 'approval' : 'approvals'} pending →
                            </Link>
                        )}
                        <LayerPicker user={user} label={label} onChange={(v) => setLayer(v)} />
                    </>
                }
            />
            <p className="m-0 mb-4 text-[13px] text-muted-foreground">
                {user
                    ? `${label}'s rules apply after the account's: a deny in either layer wins, an allow list narrows what the account allows, and approvals from both apply.`
                    : 'The account layer applies to every call, with or without a user.'}
            </p>
            <PolicyEditor user={user} label={label} />
        </>
    );
}
