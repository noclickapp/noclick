// Connecting the owner's own agent (Claude Code, Cursor, Codex…) to a hosted MCP link, as the chat's cards draw it:
// that agent's steps with the link to copy (the agent is a quiet menu beside the steps: picking another swaps them in
// place, and with none named yet the agents are offered to pick), then whether it has connected, pushed the moment it
// does. One drawing for every link the chat hands out: a workflow's MCP node (the setup card) and a server NoClick
// hosts on the platform (an MCP server's card).
import { useCallback, useEffect, useState } from 'react';
import { Check, ChevronDown, Copy } from 'lucide-react';
import { LiveDot, PILL_PRIMARY, PILL_QUIET, PILL_SECONDARY, Status } from '@/ui/chat/primitives';
import { NodeMark } from '@/ui/primitives';
import { ACCOUNT_MENU_ITEM } from '@/ui/accountParts';
import { MENU_SURFACE } from '@/ui/menus';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/ui/dropdown-menu';
import { mcpClientGuides, TerminalBlock, type ClientGuide } from '@/ui/MCPSetupModal';
import { MCP_QUICK_STEPS, connectHintFor, mcpClientFor } from '@/lib/mcpQuickSteps';
import { describeClient, type McpConnectState } from '@/lib/mcpConnectState';
import { cn } from '@/ui/utils';

const SECTION = 'mb-2 text-[12.5px] text-muted-foreground';

/** Decided once, when the card first knows: a setup that already worked opens as its receipt. */
export function useFolded(known: boolean, done: boolean): [boolean, (folded: boolean) => void] {
    const [folded, setFolded] = useState<boolean | null>(null);
    useEffect(() => {
        if (known && folded === null) setFolded(done);
    }, [known, done, folded]);
    return [folded ?? false, setFolded];
}

/** The agent a key or a name says (the coordinator writes either, a client introduces itself by its own). */
export function guideFor(keyOrName: string | null | undefined): ClientGuide | undefined {
    const client = mcpClientFor(keyOrName);
    return client && mcpClientGuides().find((g) => g.key === client.key);
}

export function ClientTile({ guide }: { guide?: ClientGuide }) {
    const Icon = guide?.BrandIcon;
    return (
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-foreground/[0.05] ring-1 ring-inset ring-foreground/[0.06]">
            {Icon ? <Icon size={22} /> : <NodeMark type="mcp-server" size="md" />}
        </span>
    );
}

/** The agent the steps are for, as a quiet menu in their heading: picking another swaps the steps in place. */
function ClientMenu({ client, onPick }: { client: ClientGuide; onPick: (guide: ClientGuide) => void }) {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                className="-mx-1 inline-flex items-center gap-0.5 rounded-md px-1 text-foreground/90 transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                data-testid="setup-client-menu"
            >
                {client.label}
                <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" sideOffset={6} onCloseAutoFocus={(e) => e.preventDefault()} className={cn('w-56 rounded-2xl p-1.5 duration-100', MENU_SURFACE)}>
                {mcpClientGuides().map((g) => (
                    <DropdownMenuItem key={g.key} onSelect={() => onPick(g)} className={cn(ACCOUNT_MENU_ITEM, 'gap-2.5 py-1.5 text-[13.5px]')}>
                        <g.Icon size={15} />
                        {g.label}
                        {g.key === client.key && <Check className="ml-auto h-3.5 w-3.5 text-muted-foreground" />}
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    );
}

function useCopy(): [boolean, (value: string) => void] {
    const [copied, setCopied] = useState(false);
    const copy = useCallback((value: string) => {
        void navigator.clipboard?.writeText(value);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
    }, []);
    return [copied, copy];
}

export function CopyButton({ value, label = 'Copy' }: { value: string; label?: string }) {
    const [copied, copy] = useCopy();
    return (
        <button type="button" className={PILL_SECONDARY} onClick={() => copy(value)}>
            {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            {copied ? 'Copied' : label}
        </button>
    );
}

/** A value to paste somewhere (a server URL), with its copy button. */
export function CopyCode({ value }: { value: string }) {
    const [copied, copy] = useCopy();
    return (
        <div className="flex items-center gap-2 rounded-lg bg-foreground/[0.05] py-1.5 pl-3 pr-1.5">
            <code className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-foreground/85">{value}</code>
            <button type="button" className={cn(PILL_QUIET, 'h-7 px-2.5')} onClick={() => copy(value)}>
                <Copy className="h-3.5 w-3.5" />
                {copied ? 'Copied' : 'Copy'}
            </button>
        </div>
    );
}

/** The agent's steps to add the link (`url`, null while it's made), under "Add it to <agent>"; with no agent yet, the
 *  agents to pick from. */
export function McpClientSteps({
    client,
    onPick,
    url,
    linkError,
    serverName,
}: {
    client: ClientGuide | undefined;
    onPick: (guide: ClientGuide) => void;
    url: string | null;
    linkError?: string | null;
    serverName: string;
}) {
    return (
        <div>
            <p className={SECTION}>
                {client ? (
                    <>
                        Add it to <ClientMenu client={client} onPick={onPick} />
                    </>
                ) : (
                    'Which agent will use it?'
                )}
            </p>
            {client && !linkError && (
                <ol className="space-y-2.5">
                    {(MCP_QUICK_STEPS[client.key] ?? MCP_QUICK_STEPS.other)(url ?? '…', serverName).map((step, i) => (
                        <li key={i} className="flex gap-3">
                            <span className="mt-px grid h-5 w-5 shrink-0 place-items-center rounded-full text-[11px] font-medium tabular-nums text-muted-foreground ring-1 ring-inset ring-foreground/20">{i + 1}</span>
                            <div className="min-w-0 flex-1 space-y-1.5">
                                <p className="text-[14px] leading-snug text-foreground">{step.text}</p>
                                {!url ? (
                                    step.code && <Status state="working">Making your link</Status>
                                ) : (
                                    <>
                                        {step.code &&
                                            (step.terminal ? (
                                                <TerminalBlock code={step.code} />
                                            ) : step.code.includes('\n') ? (
                                                <pre className="overflow-x-auto rounded-lg bg-foreground/[0.05] px-3 py-2 font-mono text-[12px] leading-relaxed text-foreground/85">{step.code}</pre>
                                            ) : (
                                                <CopyCode value={step.code} />
                                            ))}
                                        {step.link && (
                                            <a href={step.link.href} className={PILL_PRIMARY}>
                                                {step.link.label}
                                            </a>
                                        )}
                                    </>
                                )}
                            </div>
                        </li>
                    ))}
                </ol>
            )}
            {linkError && <p className="text-[13px] text-red-600 dark:text-red-400">{linkError}</p>}
            {!client && (
                <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Your agent">
                    {mcpClientGuides().map((g) => (
                        <button
                            key={g.key}
                            type="button"
                            role="radio"
                            aria-checked={false}
                            onClick={() => onPick(g)}
                            className="inline-flex h-8 items-center gap-1.5 rounded-full border border-border px-3 text-[13px] text-foreground/85 transition-colors hover:bg-foreground/[0.04] dark:border-foreground/[0.12]"
                        >
                            <g.Icon size={14} />
                            {g.label}
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}

/** Whether `agent` has connected: checking, connected (with what it sees, and `next`, what to do now), a link that was
 *  replaced, or waiting with what makes that agent connect (and, after a while, how to check). */
export function McpConnectStatus({ client, agent, state, read, next }: { client: ClientGuide | undefined; agent: string; state: McpConnectState; read: boolean; next: string }) {
    const hint = connectHintFor(client?.key ?? 'other');
    return (
        <div aria-live="polite" data-testid="setup-mcp-status" data-phase={state.phase}>
            {!read ? (
                <Status state="working">Checking the link</Status>
            ) : state.phase === 'connected' ? (
                <div className="space-y-1">
                    <Status state="done">
                        {describeClient(state, agent)} connected{state.toolCount != null ? ` and sees ${state.toolCount} ${state.toolCount === 1 ? 'tool' : 'tools'}` : ''}
                    </Status>
                    <p className="text-[13.5px] text-foreground/85">{next}</p>
                </div>
            ) : state.phase === 'inactive' ? (
                <Status state="failed">This link was replaced. Copy the new one into {agent}.</Status>
            ) : (
                <div className="space-y-1.5">
                    <span className="inline-flex items-center gap-2 text-[13.5px] text-foreground/85">
                        <LiveDot />
                        Waiting for {agent} to connect
                    </span>
                    <p className="text-[13px] leading-snug text-muted-foreground">{hint.trigger}</p>
                    {state.phase === 'waiting_long' && hint.check && (
                        <div className="space-y-1.5">
                            <p className="text-[13px] text-muted-foreground">{hint.check.text}</p>
                            {hint.check.code && (hint.check.terminal ? <TerminalBlock code={hint.check.code} /> : <CopyCode value={hint.check.code} />)}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
