// The first thing an empty console shows: one prompt to paste into a coding agent, which installs the SDK, trades
// the prompt's one-time setup code for a key that goes straight into the project's .env (so the agent never sees
// the key) and builds the agent; then the page watches for it. Agents renders it while the account has none;
// /quickstart shows it any time.
import { useEffect, useState, type ReactNode } from 'react';
import { ArrowUpRight, Check, Copy } from 'lucide-react';
import { Link } from 'react-router';
import { HAIRLINE, LiveDot, NodeMark, SURFACE } from '@/ui/primitives';
import { ClineMark, GeminiMark, GithubCopilotMark, GooseMark, WindsurfMark } from '@/ui/codingAgentMarks';
import { CursorMark } from '@/ui/CursorMark';
import { cn } from '@/ui/utils';
import { DISPLAY } from '@/ui/titles';
import { ALL_USERS, Agent } from 'noclick';
import { useSlot } from '@/slots';
import { createKey, createSetupCode, fullAccessScopes, type KeyView, type SetupCode } from '@/sdk/owner';
import { INSTALL_TABS, OPERATIONS_EMPTY, coderPrompt, envExport, snippetTabs } from '@/screens/console/lib/snippets';
import { useAccount, useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { CodeSnippet } from './ui/CodeSnippet';
import { ConsoleButton } from './ui/Button';
import { OwnerOnlyNote } from './ui/OwnerOnlyNote';
import { LEAD, TITLE } from './ui/PageHeader';
import { useOwnerOnly } from './ownerOnly';
import { TERMS } from './slots';

export const QUICKSTART_KEY_NAME = 'quickstart';
export const FIRST_AGENT_POLL_MS = 5_000;

/**
 * Put `text` on the clipboard. A promise is handed to the clipboard inside the
 * click, because Safari refuses a write that starts after an await.
 */
export async function copyToClipboard(text: string | Promise<string>): Promise<void> {
    if (typeof text === 'string') return navigator.clipboard.writeText(text);
    await navigator.clipboard.write([new ClipboardItem({ 'text/plain': text.then((t) => new Blob([t], { type: 'text/plain' })) })]);
}

const LOGO = 'h-5 w-5 text-foreground/85';

/** The agents people paste it into most, most used first; the prompt works in any that can run a command. */
const CODING_AGENTS: { label: string; mark: ReactNode }[] = [
    { label: 'Claude Code', mark: <NodeMark type="agent:claude-code" size="md" /> },
    { label: 'Codex', mark: <NodeMark type="agent:codex" size="md" /> },
    { label: 'Cursor', mark: <span className={LOGO}><CursorMark size={20} /></span> },
    { label: 'Gemini CLI', mark: <GeminiMark size={20} /> },
    { label: 'GitHub Copilot', mark: <GithubCopilotMark size={20} className={LOGO} /> },
    { label: 'OpenCode', mark: <NodeMark type="agent:opencode" size="md" /> },
    { label: 'Windsurf', mark: <WindsurfMark size={20} className={LOGO} /> },
    { label: 'Cline', mark: <ClineMark size={20} className={LOGO} /> },
    { label: 'Goose', mark: <GooseMark size={20} className={LOGO} /> },
    { label: 'Hermes', mark: <NodeMark type="agent:hermes" size="md" /> },
    { label: 'OpenClaw', mark: <NodeMark type="agent:openclaw" size="md" /> },
];

/** The agents the prompt is written for: their marks, named on hover, and the rest in a word. */
export function WorksWith() {
    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <ul aria-label="Works with" className="m-0 flex list-none flex-wrap items-center gap-1.5 p-0">
                {CODING_AGENTS.map((agent) => (
                    <li key={agent.label} title={agent.label} aria-label={agent.label} className="grid h-9 w-9 place-items-center rounded-[10px] bg-foreground/[0.05]">
                        {agent.mark}
                    </li>
                ))}
            </ul>
            <span className="text-[13px] text-foreground/60 dark:text-foreground/45">or any agent that can run commands</span>
        </div>
    );
}

/**
 * Copy the coding-agent prompt. Each copy makes a fresh setup code inside the click (a code works once, and the
 * last one may be spent), so a prompt is only ever made to be pasted.
 */
export function useCopyPrompt() {
    const { client, apiUrl } = useConsole();
    const [setup, setSetup] = useState<SetupCode | null>(null);
    const [creating, setCreating] = useState(false);
    const [error, setError] = useState<unknown>(null);
    const [state, setState] = useState<'idle' | 'copied' | 'copy-failed'>('idle');
    const copy = async () => {
        setCreating(true);
        setError(null);
        let made: SetupCode | null = null;
        const minting = createSetupCode(client).then((code) => (made = code));
        try {
            await copyToClipboard(minting.then((code) => coderPrompt(code.code, apiUrl)));
            setSetup(made);
            setState('copied');
        } catch (err) {
            // No code: say why. A code but no clipboard: the prompt shows it, to copy by hand.
            if (made) {
                setSetup(made);
                setState('copy-failed');
            } else {
                setError(err);
                setState('idle');
            }
        } finally {
            setCreating(false);
        }
    };
    const prompt = setup ? coderPrompt(setup.code, apiUrl) : null;
    return { state, setup, prompt, creating, error, copy };
}

const expiry = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

/** The Copy prompt button. */
export function CopyPromptButton({ copier }: { copier: ReturnType<typeof useCopyPrompt> }) {
    const { state, creating, copy } = copier;
    return (
        <ConsoleButton
            variant="primary"
            className="h-10 w-fit shrink-0 px-5 text-[13px]"
            icon={state === 'copied' ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
            onClick={() => void copy()}
            disabled={creating}
        >
            {creating ? 'Making a code…' : state === 'copied' ? 'Copied' : 'Copy prompt'}
        </ConsoleButton>
    );
}

/** What a copy did: when its code runs out, or why there's no code. */
export function CopyPromptStatus({ copier }: { copier: ReturnType<typeof useCopyPrompt> }) {
    const { state, setup, error } = copier;
    if (error !== null) {
        return (
            <p role="alert" className="m-0 text-[13px] text-red-600 dark:text-red-400">
                Couldn&apos;t make a setup code: {error instanceof Error ? error.message : String(error)}
            </p>
        );
    }
    return (
        <p className="m-0 text-[13px] text-foreground/70 dark:text-foreground/50" aria-live="polite">
            {state === 'copied' && setup
                ? `Copied. Paste it into your coding agent; its code works once, until ${expiry(setup.expires_at)}.`
                : state === 'copy-failed'
                  ? 'Your browser blocked the copy. Copy the prompt below by hand.'
                  : 'Each copy carries a new code that works once, for 30 minutes.'}
        </p>
    );
}

/** The prompt itself, only where the browser refused the copy, to copy by hand. */
export function HandCopyPrompt({ copier }: { copier: ReturnType<typeof useCopyPrompt> }) {
    return copier.state === 'copy-failed' ? <PromptText copier={copier} className="max-h-48 overflow-auto rounded-lg bg-foreground/[0.04] px-3 py-2.5" /> : null;
}

/** The button and what it did, stacked (the New agent dialog). */
export function CopyPromptAction({ copier }: { copier: ReturnType<typeof useCopyPrompt> }) {
    return (
        <div className="flex flex-col gap-3">
            <CopyPromptButton copier={copier} />
            <CopyPromptStatus copier={copier} />
            <HandCopyPrompt copier={copier} />
        </div>
    );
}

/** The prompt as it will be pasted. */
function PromptText({ copier, className }: { copier: ReturnType<typeof useCopyPrompt>; className?: string }) {
    return (
        <pre aria-label="Prompt" className={cn('m-0 whitespace-pre-wrap break-words font-mono text-[12px] leading-[1.65] text-foreground/75 dark:text-foreground/65', className)}>
            {copier.prompt}
        </pre>
    );
}

/** The manual steps' key: one per visit, made on request; the raw value is only in memory. */
export function useQuickstartKey() {
    const { client } = useConsole();
    const account = useAccount();
    const [key, setKey] = useState<KeyView | null>(null);
    const [pending, setPending] = useState<Promise<KeyView> | null>(null);
    const [error, setError] = useState<unknown>(null);
    const create = (): Promise<KeyView> => {
        if (key) return Promise.resolve(key);
        if (pending) return pending;
        setError(null);
        const next = createKey(client, { name: QUICKSTART_KEY_NAME, scopes: fullAccessScopes(account.data?.meta.scopes ?? []) });
        setPending(next);
        next.then(
            (created) => {
                setKey(created);
                invalidateV1('keys');
                void account.refresh();
            },
            (err: unknown) => setError(err)
        ).finally(() => setPending(null));
        return next;
    };
    return { key, raw: key?.raw_key ?? null, creating: pending !== null, error, create };
}

/** A numbered step on a thin rail that runs down to the next one. */
function Step({ n, title, action, last = false, children }: { n: number; title: string; action?: ReactNode; last?: boolean; children: ReactNode }) {
    return (
        <li className="relative flex gap-4 pb-7 last:pb-0">
            {!last && <span aria-hidden className="absolute bottom-0 left-3 top-8 w-px bg-border dark:bg-foreground/[0.08]" />}
            <span className="relative mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border bg-background text-[12px] font-semibold tabular-nums text-foreground/80 dark:border-foreground/[0.12]">
                {n}
            </span>
            <div className="flex min-w-0 flex-1 flex-col gap-2.5">
                <div className="flex min-h-6 items-center justify-between gap-3">
                    <span className="text-[14px] font-medium text-foreground">{title}</span>
                    {action}
                </div>
                {children}
            </div>
        </li>
    );
}

function FirstAgentWatch() {
    const { client } = useConsole();
    const account = useAccount();
    const href = useConsoleHref();
    const known = (account.data?.counts.agents ?? 0) > 0;
    const first = useV1(known ? null : 'agents?first', () => Agent.listPage({ client, userFilter: ALL_USERS, limit: 1 }), { pollMs: FIRST_AGENT_POLL_MS });
    const found = (first.data?.data.length ?? 0) > 0;
    const { refresh } = account;
    useEffect(() => {
        if (found) void refresh();
    }, [found, refresh]);
    if (known || found) {
        return (
            <Link to={href('')} className="inline-flex items-center gap-1.5 text-[13px] font-medium text-foreground transition-colors hover:text-foreground/80">
                Your agents are live <ArrowUpRight className="h-3.5 w-3.5" />
            </Link>
        );
    }
    return (
        <p className="m-0 inline-flex items-center gap-2.5 text-[13px] text-foreground/70 dark:text-foreground/50" aria-live="polite">
            <LiveDot className="h-2 w-2 [&>span]:h-2 [&>span]:w-2" />
            Waiting for your first agent. This page becomes your agents list when it appears.
        </p>
    );
}

export function Quickstart() {
    const copier = useCopyPrompt();
    const quickKey = useQuickstartKey();
    const [lang, setLang] = useState('python');
    const example = snippetTabs(OPERATIONS_EMPTY);
    const Terms = useSlot(TERMS);
    const ownerCan = useOwnerOnly();
    // The prompt carries a one-time code only the signed-in owner can mint; without it the steps stand alone.
    const prompted = ownerCan('setupCode');
    return (
        <div className="flex flex-col gap-10">
            <header>
                <h1 className={cn('m-0', TITLE)}>Build your first agent</h1>
                <p className={cn('m-0 mt-1.5 max-w-2xl', LEAD)}>
                    {prompted
                        ? 'Paste one prompt into your coding agent. It installs NoClick, saves a key to your project without ever seeing it, and builds the agent with you.'
                        : 'Install NoClick, give it one of your account’s keys, and run the example.'}
                </p>
            </header>

            {prompted && (
            <div className="flex flex-col gap-3">
                <section aria-label="Copy a prompt for your coding agent" className={cn(SURFACE, 'flex flex-col gap-5 p-6')}>
                    <div className="flex flex-col gap-3">
                        <h2 className={cn(DISPLAY, 'm-0 text-[28px] leading-[1.1] text-foreground')}>
                            For your <span className="italic">coding agent</span>
                        </h2>
                        <WorksWith />
                    </div>
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                        <CopyPromptButton copier={copier} />
                        <CopyPromptStatus copier={copier} />
                    </div>
                    <HandCopyPrompt copier={copier} />
                </section>
                <Terms action="copying this prompt" />
            </div>
            )}

            <section aria-label="Or set it up yourself" className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,14rem)_minmax(0,1fr)]">
                <div>
                    <h2 className="m-0 text-[16px] font-semibold tracking-tight text-foreground">{prompted ? 'Or set it up yourself' : 'Set it up'}</h2>
                    <p className="m-0 mt-1.5 text-[13px] leading-5 text-foreground/70 dark:text-foreground/60">Three steps in Python or TypeScript. The example creates an agent once and messages it.</p>
                </div>
                <ol className="m-0 flex list-none flex-col p-0">
                    <Step n={1} title="Install the SDK">
                        <CodeSnippet tabs={INSTALL_TABS} tab={lang} onTabChange={setLang} />
                    </Step>
                    <Step
                        n={2}
                        title="Set your API key"
                        action={
                            !quickKey.raw &&
                            ownerCan('keys') && (
                                <ConsoleButton size="sm" variant="primary" onClick={() => void quickKey.create().catch(() => undefined)} disabled={quickKey.creating}>
                                    {quickKey.creating ? 'Creating…' : 'Create key'}
                                </ConsoleButton>
                            )
                        }
                    >
                        <CodeSnippet code={envExport(quickKey.raw ?? 'nk_live_…')} language="bash" />
                        {quickKey.raw && <p className="m-0 text-[13px] text-foreground/70 dark:text-foreground/60">Copy it now; the key isn&apos;t shown again.</p>}
                        {!ownerCan('keys') && <OwnerOnlyNote what="keys" />}
                    </Step>
                    <Step n={3} title="Create an agent and message it" last>
                        <CodeSnippet tabs={example} tab={lang} onTabChange={setLang} />
                    </Step>
                </ol>
            </section>

            <div className={cn('border-t pt-6', HAIRLINE)}>
                <FirstAgentWatch />
            </div>
        </div>
    );
}
