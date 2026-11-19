// Per-client MCP setup guides, modeled on linear.app/docs/mcp (numbered steps, CLI commands, JSON snippets, one-click
// deeplinks). One generic modal (MCPSetupModal) serves NoClick's own MCP server (a static URL and OAuth) and a host's
// own links (minting, rotation and the live connect status go in its slots). The snippets and what makes each client
// connect come from lib/mcpQuickSteps.ts (MCP_CLIENTS), the one source the docs are generated from too. Each client is
// drawn by its own mark (ui/codingAgentMarks.tsx); the coding harnesses' art is the host's (`mcp.client.marks`), else
// the protocol's mark stands in. The tab rail is a keyboard-navigable ARIA tablist; arrows work from anywhere in it.
import { useEffect, useRef, useState, type ComponentType, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Check, Copy, Loader2, X } from 'lucide-react';
import { standing } from '@/slots';
import { MCP_CLIENTS, type GuideBlock } from '@/lib/mcpQuickSteps';
import { BUTTON_SECONDARY } from '@/ui/buttons';
import { ClaudeColorMark, ClaudeMark, McpMark, OpenAIMark, WindsurfMark } from '@/ui/codingAgentMarks';
import { CursorMark } from '@/ui/CursorMark';
import { MCP_CLIENT_MARKS } from '@/ui/slots';
import { DISPLAY } from '@/ui/titles';
import { cn } from '@/ui/utils';

// Official brand marks from simple-icons (CC0).
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

export interface ClientGuide {
    key: string;
    label: string;
    Icon: ComponentType<{ size?: number }>;
    /** Its mark in its own colours, where it stands alone (a card's tile); the rail's `Icon` is quieted. */
    BrandIcon: ComponentType<{ size?: number }>;
    blocks: (url: string, name: string) => GuideBlock[];
}

const CLIENT_ICONS: Record<string, ComponentType<{ size?: number }>> = {
    claude: ClaudeMark,
    chatgpt: OpenAIMark,
    codex: OpenAIMark,
    cursor: CursorMark,
    vscode: VSCodeIcon,
    windsurf: WindsurfMark,
    zed: ZedIcon,
};
const GENERIC_ICON: ComponentType<{ size?: number }> = McpMark;
const BRAND_ICONS: Record<string, ComponentType<{ size?: number }>> = { claude: ClaudeColorMark };

/** The clients' guides (lib/mcpQuickSteps, the one source), each with its marks: the modal's rail, a setup's finale
 *  and the chat's MCP server card. A coding harness's are the host's art for it, where it has some. */
export function mcpClientGuides(): ClientGuide[] {
    const art = standing(MCP_CLIENT_MARKS);
    return MCP_CLIENTS.map((c) => {
        const Icon = art[c.key]?.Icon ?? CLIENT_ICONS[c.key] ?? GENERIC_ICON;
        return { key: c.key, label: c.label, Icon, BrandIcon: art[c.key]?.BrandIcon ?? BRAND_ICONS[c.key] ?? Icon, blocks: c.guide };
    });
}

export { MCP_QUICK_STEPS, type QuickStep } from '@/lib/mcpQuickSteps';

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
    const [guides] = useState(mcpClientGuides);
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
            if (e.key === 'ArrowDown') next = (activeIndexRef.current + 1) % guides.length;
            else if (e.key === 'ArrowUp') next = (activeIndexRef.current - 1 + guides.length) % guides.length;
            else if (e.key === 'Home') next = 0;
            else if (e.key === 'End') next = guides.length - 1;
            if (next === null) return;
            e.preventDefault();
            e.stopPropagation();
            setActiveIndex(next);
            tabRefs.current[next]?.focus();
        };
        document.addEventListener('keydown', onKey, true);
        return () => document.removeEventListener('keydown', onKey, true);
    }, [open, onClose, guides]);

    // Focus the active tab on open so arrow keys work immediately.
    useEffect(() => {
        if (open) requestAnimationFrame(() => tabRefs.current[activeIndexRef.current]?.focus());
    }, [open]);

    if (!open || typeof document === 'undefined') return null;

    const client = guides[activeIndex];
    const displayUrl = url ?? '...';

    // Left/Right on the rail itself; Up/Down/Home/End are handled globally.
    const onTablistKeyDown = (e: ReactKeyboardEvent) => {
        let next: number | null = null;
        if (e.key === 'ArrowRight') next = (activeIndex + 1) % guides.length;
        else if (e.key === 'ArrowLeft') next = (activeIndex - 1 + guides.length) % guides.length;
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
                        {guides.map((c, i) => (
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
                    <button type="button" onClick={onClose} className={cn(BUTTON_SECONDARY, 'ml-auto')}>
                        Done
                    </button>
                </div>
            </div>
        </>,
        document.body,
    );
}
