// Per-client MCP setup guides, modeled on linear.app/docs/mcp (numbered
// steps, CLI commands, JSON snippets, one-click deeplinks). One generic modal
// (MCPSetupModal) serves the platform's own NoClick MCP server (static URL +
// OAuth, opened from the command palette); a hosted deployment also mounts it
// for a hosting-mode MCP node's public link, adding minting, rotation and the
// live connect status through the modal's slots. Client icons: @lobehub/icons (Mono
// variants where the brand mark is too dark for our theme), official
// simple-icons paths inline for VS Code/Zed. Tab rail is a keyboard-navigable
// ARIA tablist; arrows work from anywhere in the modal. The snippets and what
// makes each client connect come from data/mcpQuickSteps.ts (MCP_CLIENTS), the
// one source the docs are generated from too.

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Check, Copy, Loader2, X } from 'lucide-react';
import { Claude, MCP, OpenAI, Windsurf as WindsurfIcon } from '@lobehub/icons';
import { HARNESS_BRANDS } from '~/lib/harnessBrand';
import { CursorMark } from '~/components/shared/CursorMark';
import { MCP_CLIENTS, type GuideBlock } from '~/data/mcpQuickSteps';
import { noclickMcp } from '~/lib/noclickMcp';
import { KeyHint } from '~/components/shared/KeyHint';
import { BUTTON_SECONDARY } from '~/components/shell/buttons';
import { DISPLAY } from '~/components/shell/titles';
import { cn } from '~/lib/utils';

// Official brand marks from simple-icons (CC0) — not in @lobehub/icons.
function VSCodeIcon({ size = 16 }: { size?: number }) {
    return (
        <svg viewBox="0 0 24 24" width={size} height={size} fill="currentColor" aria-hidden>
            <path d="M23.15 2.587L18.21.21a1.494 1.494 0 0 0-1.705.29l-9.46 8.63-4.12-3.128a.999.999 0 0 0-1.276.057L.327 7.261A1 1 0 0 0 .326 8.74L3.899 12 .326 15.26a1 1 0 0 0 .001 1.479L1.65 17.94a.999.999 0 0 0 1.276.057l4.12-3.128 9.46 8.63a1.492 1.492 0 0 0 1.704.29l4.942-2.377A1.5 1.5 0 0 0 24 20.06V3.939a1.5 1.5 0 0 0-.85-1.352zm-5.146 14.861L10.826 12l7.178-5.448v10.896z" />
        </svg>
    );
}

function ZedIcon({ size = 16 }: { size?: number }) {
    return (
        <svg viewBox="0 0 24 24" width={size} height={size} fill="currentColor" aria-hidden>
            <path d="M2.25 1.5a.75.75 0 0 0-.75.75v16.5H0V2.25A2.25 2.25 0 0 1 2.25 0h20.095c1.002 0 1.504 1.212.795 1.92L10.764 14.298h3.486V12.75h1.5v1.922a1.125 1.125 0 0 1-1.125 1.125H9.264l-2.578 2.578h11.689V9h1.5v9.375a1.5 1.5 0 0 1-1.5 1.5H5.185L2.562 22.5H21.75a.75.75 0 0 0 .75-.75V5.25H24v16.5A2.25 2.25 0 0 1 21.75 24H1.655C.653 24 .151 22.788.86 22.08L13.19 9.75H9.75v1.5h-1.5V9.375A1.125 1.125 0 0 1 9.375 8.25h5.314l2.625-2.625H5.625V15h-1.5V5.625a1.5 1.5 0 0 1 1.5-1.5h13.19L21.438 1.5z" />
        </svg>
    );
}

// Real harness brand marks from the shared asset map (plain strings, no
// registry weight). monochrome art inverts on light surfaces.
// Wide/inset art renders undersized when contain-fit into the rail's small
// square — per-mark upscale on top of the shared inset.
const RAIL_MARK_SCALE: Record<string, number> = {
    'claude-code': 1.45,
    openclaw: 1.35,
};

const harnessMarkIcon = (slug: keyof typeof HARNESS_BRANDS, brand = false) =>
    function HarnessMark({ size = 16 }: { size?: number }) {
        const b = HARNESS_BRANDS[slug];
        const scale = (b.inset ?? 1) * (RAIL_MARK_SCALE[slug] ?? 1);
        // Grayscaled so colored brand art (clawd's salmon, hermes' gold) sits quietly beside the mono client icons in
        // the rail; `brand` keeps its colour, where the mark alone stands for the client (the chat's connect card).
        const quiet = brand ? '' : ' grayscale opacity-80';
        return (
            <span
                className="inline-flex shrink-0 items-center justify-center"
                style={{ width: size, height: size }}
            >
                <img
                    src={b.markSrc}
                    alt=""
                    className={b.monochrome ? `h-full w-full object-contain${quiet} invert dark:invert-0` : `h-full w-full object-contain${quiet}`}
                    style={scale !== 1 ? { transform: `scale(${scale})` } : undefined}
                />
            </span>
        );
    };

export interface ClientGuide {
    key: string;
    label: string;
    Icon: React.ComponentType<{ size?: number }>;
    /** Its mark in its own colours, where it stands alone (a card's tile); the rail's `Icon` is quieted. */
    BrandIcon: React.ComponentType<{ size?: number }>;
    blocks: (url: string, name: string) => GuideBlock[];
}

const CLIENT_ICONS: Record<string, React.ComponentType<{ size?: number }>> = {
    claude: Claude,
    'claude-code': harnessMarkIcon('claude-code'),
    chatgpt: OpenAI,
    codex: OpenAI,
    opencode: harnessMarkIcon('opencode'),
    openclaw: harnessMarkIcon('openclaw'),
    hermes: harnessMarkIcon('hermes'),
    cursor: CursorMark,
    vscode: VSCodeIcon,
    windsurf: WindsurfIcon,
    zed: ZedIcon,
};
const GENERIC_ICON = MCP as unknown as React.ComponentType<{ size?: number }>;
const BRAND_ICONS: Record<string, React.ComponentType<{ size?: number }>> = {
    claude: Claude.Color,
    'claude-code': harnessMarkIcon('claude-code', true),
    opencode: harnessMarkIcon('opencode', true),
    openclaw: harnessMarkIcon('openclaw', true),
    hermes: harnessMarkIcon('hermes', true),
};

// The clients' guides (data/mcpQuickSteps, the one source), each with its icon: the modal's rail, the Setup finale
// and the coordinator's setup card.
export const MCP_CLIENT_GUIDES: ClientGuide[] = MCP_CLIENTS.map((c) => {
    const Icon = CLIENT_ICONS[c.key] ?? GENERIC_ICON;
    return { key: c.key, label: c.label, Icon, BrandIcon: BRAND_ICONS[c.key] ?? Icon, blocks: c.guide };
});

export { MCP_QUICK_STEPS, type QuickStep } from '~/data/mcpQuickSteps';

/** Click-anywhere-to-copy code block: the copy affordance lives top-right as
 *  an indicator (swaps to Copied), the whole block is the button. `action`
 *  renders extra controls in the label row (e.g. the URL rotate button). */
export function CopyBlock({ title, code, action }: { title: string; code: string; action?: ReactNode }) {
    const [copied, setCopied] = useState(false);
    const copy = () => {
        navigator.clipboard.writeText(code);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
    };
    return (
        <div>
            <div className="mb-1.5 flex items-center justify-between gap-2">
                <span className="text-[13px] font-medium text-foreground/85">{title}</span>
                <span className="flex items-center gap-1.5">
                    {action}
                    <span className={cn('inline-flex items-center gap-1 text-[12px]', copied ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground')}>
                        {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                        {copied ? 'Copied' : 'Copy'}
                    </span>
                </span>
            </div>
            <button
                type="button"
                onClick={copy}
                title="Copy to clipboard"
                className="scrollbar-subtle block w-full cursor-pointer overflow-x-auto rounded-xl bg-foreground/[0.04] px-3.5 py-3 text-left ring-1 ring-inset ring-border transition-colors hover:bg-foreground/[0.06] dark:ring-foreground/[0.08]"
            >
                <pre className="m-0 font-mono text-[12.5px] leading-relaxed text-foreground">
                    <code>{code}</code>
                </pre>
            </button>
        </div>
    );
}

/** Click-anywhere-to-copy terminal command ($-prefixed prompt styling). */
export function TerminalBlock({ code }: { code: string }) {
    const [copied, setCopied] = useState(false);
    const copy = () => {
        navigator.clipboard.writeText(code);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
    };
    return (
        <button
            type="button"
            onClick={copy}
            title="Copy to clipboard"
            className="relative block w-full cursor-pointer rounded-lg border border-white/[0.08] bg-black text-left transition-colors hover:border-white/20"
        >
            {/* A long command (a link's secret path) wraps: scrolled sideways, its start or end was out of view. */}
            <pre className="m-0 flex items-start gap-2 px-3.5 py-3 pr-20 text-[12.5px] leading-relaxed">
                <span className="select-none text-emerald-400/80">$</span>
                <code className="min-w-0 whitespace-pre-wrap text-zinc-100 [overflow-wrap:anywhere]">{code}</code>
            </pre>
            <span className="pointer-events-none absolute inset-y-px right-px flex items-start rounded-r-lg bg-gradient-to-l from-black via-black/90 to-transparent py-3 pl-8 pr-3.5 text-[11px] select-none text-zinc-500">
                {copied ? 'Copied' : 'Copy'}
            </span>
        </button>
    );
}

export function GuideBlockView({ block }: { block: GuideBlock }) {
    switch (block.kind) {
        case 'code':
            return <CopyBlock title={block.title} code={block.code} />;
        case 'note':
            return <p className="text-[13.5px] leading-relaxed text-muted-foreground">{block.text}</p>;
        case 'steps':
            return (
                <ol className="list-decimal space-y-2 pl-5 text-[13.5px] leading-relaxed text-foreground/85 marker:text-muted-foreground">
                    {block.steps.map(s => (
                        <li key={s}>{s}</li>
                    ))}
                </ol>
            );
        case 'link':
            return (
                <div className="flex items-center gap-2.5">
                    <a href={block.href} className={cn(BUTTON_SECONDARY, 'h-8 px-3.5 text-[13px]')}>
                        {block.label}
                    </a>
                    {block.trailing && <span className="text-[12.5px] text-muted-foreground">{block.trailing}</span>}
                </div>
            );
    }
}

export interface MCPSetupModalProps {
    open: boolean;
    onClose: () => void;
    /** Resolved server URL; null while pending. */
    url: string | null;
    urlError?: string | null;
    /** Server key used in snippets (already prefixed/slugified by the caller). */
    serverName: string;
    title: string;
    intro: string;
    /** Extra control in the URL block's label row (e.g. rotate). */
    urlAction?: ReactNode;
    /** Banner under the URL block (e.g. the post-rotation warning). */
    urlNotice?: ReactNode;
    /** Rendered under the active client's guide — the hosted surface puts
     *  the live connect status here so it sits next to the snippet it judges. */
    statusFor?: (clientKey: string, clientLabel: string) => ReactNode;
}

/** Generic per-client MCP setup guide modal — shared by the hosted-link
 *  surface (MCP node) and the platform NoClick MCP (command palette). */
export function MCPSetupModal({ open, onClose, url, urlError, serverName, title, intro, urlAction, urlNotice, statusFor }: MCPSetupModalProps) {
    const [activeIndex, setActiveIndex] = useState(0);
    const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
    const activeIndexRef = useRef(0);
    activeIndexRef.current = activeIndex;

    // Escape closes and ArrowUp/Down switch clients from ANYWHERE in the
    // modal (document capture — focus is often on a copy button, the rotate
    // confirm, or nowhere at all). Suspended while a nested dialog owns keys.
    useEffect(() => {
        if (!open) return;
        const onKey = (e: KeyboardEvent) => {
            if (document.querySelector('[data-mcp-rotate-confirm]')) return;
            let next: number | null = null;
            if (e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                e.stopImmediatePropagation();
                onClose();
                return;
            }
            if (e.key === 'ArrowDown') next = (activeIndexRef.current + 1) % MCP_CLIENT_GUIDES.length;
            else if (e.key === 'ArrowUp') next = (activeIndexRef.current - 1 + MCP_CLIENT_GUIDES.length) % MCP_CLIENT_GUIDES.length;
            else if (e.key === 'Home') next = 0;
            else if (e.key === 'End') next = MCP_CLIENT_GUIDES.length - 1;
            if (next === null) return;
            e.preventDefault();
            e.stopPropagation();
            setActiveIndex(next);
            tabRefs.current[next]?.focus();
        };
        document.addEventListener('keydown', onKey, true);
        return () => document.removeEventListener('keydown', onKey, true);
    }, [open, onClose]);

    // Focus the active tab on open so arrow keys work immediately.
    useEffect(() => {
        if (open) requestAnimationFrame(() => tabRefs.current[activeIndexRef.current]?.focus());
    }, [open]);

    if (!open || typeof document === 'undefined') return null;

    const client = MCP_CLIENT_GUIDES[activeIndex];
    const displayUrl = url ?? '...';

    // Left/Right on the rail itself; Up/Down/Home/End are handled globally.
    const onTablistKeyDown = (e: React.KeyboardEvent) => {
        let next: number | null = null;
        if (e.key === 'ArrowRight') next = (activeIndex + 1) % MCP_CLIENT_GUIDES.length;
        else if (e.key === 'ArrowLeft') next = (activeIndex - 1 + MCP_CLIENT_GUIDES.length) % MCP_CLIENT_GUIDES.length;
        if (next === null) return;
        e.preventDefault();
        setActiveIndex(next);
        tabRefs.current[next]?.focus();
    };

    return createPortal(
        <>
            {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions, jsx-a11y/click-events-have-key-events */}
            <div className="fixed inset-0 z-[100] bg-foreground/[0.08] dark:bg-background/60" onMouseDown={onClose} />
            {/* The app's dialog (ShellDialog): the page's surface, a mark beside the title in the brand face, pill buttons. */}
            <div
                role="dialog"
                aria-modal="true"
                aria-label={title}
                className="fixed left-1/2 top-[7vh] z-[101] flex max-h-[86dvh] w-[calc(100vw-32px)] max-w-[820px] -translate-x-1/2 flex-col overflow-hidden rounded-2xl border border-border bg-card text-foreground shadow-lg dark:border-foreground/[0.12] dark:bg-sunken"
            >
                <div className="min-w-0 px-6 pb-5 pr-14 pt-6">
                    <h2 className={cn(DISPLAY, 'm-0 text-[32px] leading-[1.05] text-foreground')}>{title}</h2>
                    <p className="m-0 mt-2 text-[14px] leading-snug text-muted-foreground">{intro}</p>
                </div>
                <button
                    type="button"
                    onClick={onClose}
                    aria-label="Close"
                    className="absolute right-4 top-5 inline-flex h-8 w-8 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                    <X className="h-4 w-4" />
                </button>

                <div className="px-6 pb-5">
                    {url ? (
                        <div className="space-y-2">
                            <CopyBlock title="Server URL" code={url} action={urlAction} />
                            {urlNotice}
                        </div>
                    ) : urlError ? (
                        <div className="text-[13px] text-red-600 dark:text-red-400">{urlError}</div>
                    ) : (
                        <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            Creating server link…
                        </div>
                    )}
                </div>

                <div className="flex min-h-[300px] min-w-0 flex-1 border-t border-border dark:border-foreground/[0.08]">
                    <div
                        role="tablist"
                        aria-orientation="vertical"
                        aria-label="MCP clients"
                        className="scrollbar-subtle w-48 shrink-0 space-y-0.5 overflow-y-auto border-r border-border p-2 dark:border-foreground/[0.08]"
                    >
                        {MCP_CLIENT_GUIDES.map((c, i) => (
                            <button
                                key={c.key}
                                ref={el => { tabRefs.current[i] = el; }}
                                type="button"
                                role="tab"
                                aria-selected={i === activeIndex}
                                tabIndex={i === activeIndex ? 0 : -1}
                                onClick={() => setActiveIndex(i)}
                                onKeyDown={onTablistKeyDown}
                                className={cn(
                                    'flex h-9 w-full items-center gap-3 rounded-[12px] px-3 text-left text-[14px] outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring',
                                    i === activeIndex ? 'bg-foreground/[0.07] text-foreground' : 'text-foreground/70 hover:bg-foreground/[0.04] hover:text-foreground'
                                )}
                            >
                                <span className="flex h-4 w-4 shrink-0 items-center justify-center">
                                    <c.Icon size={16} />
                                </span>
                                {c.label}
                            </button>
                        ))}
                    </div>

                    <div
                        role="tabpanel"
                        aria-label={client.label}
                        className="scrollbar-subtle min-w-0 flex-1 space-y-4 overflow-y-auto px-6 py-5"
                    >
                        {client.blocks(displayUrl, serverName).map((b, i) => (
                            <GuideBlockView key={i} block={b} />
                        ))}
                        {statusFor?.(client.key, client.label)}
                    </div>
                </div>

                <div className="flex items-center justify-between gap-3 border-t border-border px-6 py-4 dark:border-foreground/[0.08]">
                    <span className="hidden items-center gap-1.5 text-[12px] text-muted-foreground sm:flex">
                        <KeyHint keys={['up', 'down']} /> Switch client
                        <span className="px-1 text-muted-foreground/50">·</span>
                        <KeyHint keys={['esc']} /> Close
                    </span>
                    <button type="button" onClick={onClose} className={cn(BUTTON_SECONDARY, 'ml-auto')}>
                        Done
                    </button>
                </div>
            </div>
        </>,
        document.body,
    );
}

/** Setup guides for NoClick's own MCP server, the one `noclickMcp()` names. Static URL; clients run the OAuth
 *  sign-in on first connect. Opened from Connect, the command palette and Connections. */
export function NoClickMCPSetupModal({ open, onClose }: { open: boolean; onClose: () => void }) {
    const { url, intro } = noclickMcp();
    return <MCPSetupModal open={open} onClose={onClose} url={url} serverName="noclick" title="Connect over MCP" intro={intro} />;
}
