// Per-client setup guides for the NoClick MCP server: numbered steps, CLI
// commands, JSON snippets, and one-click deeplinks. Client icons use
// @lobehub/icons (Mono variants where the brand mark
// is too dark for our theme), official simple-icons paths inline for VS
// Code/Zed. Tab rail is a keyboard-navigable ARIA tablist; arrows work from
// anywhere in the modal. Snippets verified against each client's current
// official docs (2026-06) — key names diverge (url vs serverUrl vs TOML);
// keep in sync when client docs move.

import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, Copy, Globe, Loader2 } from 'lucide-react';
import { Claude, MCP, OpenAI, Windsurf as WindsurfIcon } from '@lobehub/icons';
import { HARNESS_BRANDS } from '~/lib/harnessBrand';
import { cursorDeeplink } from '~/data/mcpQuickSteps';
import { mcpServerUrl } from '~/lib/hostedDefaults';

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

// Cursor's lobehub mark uses gradient fills that resolve near-black on our
// dark surface — use the official simple-icons mark in currentColor instead.
// Real harness brand marks from the shared asset map (plain strings, no
// registry weight). monochrome art inverts on light surfaces.
// Wide/inset art renders undersized when contain-fit into the rail's small
// square — per-mark upscale on top of the shared inset.
const RAIL_MARK_SCALE: Record<string, number> = {
    'claude-code': 1.45,
    openclaw: 1.35,
};

const harnessMarkIcon = (slug: keyof typeof HARNESS_BRANDS) =>
    function HarnessMark({ size = 16 }: { size?: number }) {
        const b = HARNESS_BRANDS[slug];
        const scale = (b.inset ?? 1) * (RAIL_MARK_SCALE[slug] ?? 1);
        // Grayscaled so colored brand art (clawd's salmon, hermes' gold)
        // sits quietly beside the mono client icons in the rail.
        return (
            <span
                className="inline-flex shrink-0 items-center justify-center"
                style={{ width: size, height: size }}
            >
                <img
                    src={b.markSrc}
                    alt=""
                    className={
                        b.monochrome
                            ? 'h-full w-full object-contain grayscale opacity-80 invert dark:invert-0'
                            : 'h-full w-full object-contain grayscale opacity-80'
                    }
                    style={scale !== 1 ? { transform: `scale(${scale})` } : undefined}
                />
            </span>
        );
    };

function CursorMonoIcon({ size = 16 }: { size?: number }) {
    return (
        <svg viewBox="0 0 24 24" width={size} height={size} fill="currentColor" aria-hidden>
            <path d="M11.503.131 1.891 5.678a.84.84 0 0 0-.42.726v11.188c0 .3.162.575.42.724l9.609 5.55a1 1 0 0 0 .998 0l9.61-5.55a.84.84 0 0 0 .42-.724V6.404a.84.84 0 0 0-.42-.726L12.497.131a1.01 1.01 0 0 0-.996 0M2.657 6.338h18.55c.263 0 .43.287.297.515L12.23 22.918c-.062.107-.229.064-.229-.06V12.335a.59.59 0 0 0-.295-.51l-9.11-5.257c-.109-.063-.064-.23.061-.23" />
        </svg>
    );
}

type GuideBlock =
    | { kind: 'code'; title: string; code: string }
    | { kind: 'steps'; title?: string; steps: string[] }
    | { kind: 'link'; label: string; href: string; trailing?: string }
    | { kind: 'note'; text: string };

export interface ClientGuide {
    key: string;
    label: string;
    Icon: React.ComponentType<{ size?: number }>;
    blocks: (url: string, name: string) => GuideBlock[];
}

// Exported for the Setup finale's inline connect guide (same snippets,
// different layout — the modal keeps its vertical-rail chrome).
export const MCP_CLIENT_GUIDES: ClientGuide[] = [
    {
        key: 'claude',
        label: 'Claude',
        Icon: Claude,
        blocks: url => [
            { kind: 'note', text: 'Works on claude.ai and the Claude desktop app, all plans, through custom connectors.' },
            {
                kind: 'steps',
                steps: [
                    'Open Settings → Connectors.',
                    'Choose Add custom connector (bottom of the list).',
                    'Paste the server URL and click Add.',
                ],
            },
            { kind: 'code', title: 'Server URL', code: url },
        ],
    },
    {
        key: 'claude-code',
        label: 'Claude Code',
        Icon: harnessMarkIcon('claude-code'),
        blocks: (url, name) => [
            { kind: 'code', title: 'Terminal', code: `claude mcp add --transport http ${name} ${url}` },
            { kind: 'note', text: 'Run /mcp in a Claude Code session to confirm the server is connected. To share it with your team instead, add it to .mcp.json in the project root:' },
            {
                kind: 'code',
                title: '.mcp.json',
                code: JSON.stringify({ mcpServers: { [name]: { type: 'http', url } } }, null, 2),
            },
        ],
    },
    {
        key: 'chatgpt',
        label: 'ChatGPT',
        Icon: OpenAI,
        blocks: url => [
            { kind: 'note', text: 'Custom MCP connectors need developer mode (Plus, Pro, Business, Enterprise and Edu — set up on the web app; on team plans an admin must allow it first).' },
            {
                kind: 'steps',
                steps: [
                    'Open Settings → Apps & Connectors.',
                    'Under Advanced settings, toggle Developer mode on.',
                    'Back in Apps & Connectors, click Create.',
                    'Enter a name and paste the server URL as the MCP Server URL.',
                    'Set Authentication to No Authentication, check "I trust this application", and save.',
                    'In a chat, enable the connector from the + / tools menu.',
                ],
            },
            { kind: 'code', title: 'MCP Server URL', code: url },
        ],
    },
    {
        key: 'codex',
        label: 'Codex',
        Icon: OpenAI,
        blocks: (url, name) => [
            { kind: 'code', title: 'Terminal', code: `codex mcp add ${name} --url ${url}` },
            { kind: 'note', text: 'Or configure it directly — verify with `codex mcp list`:' },
            { kind: 'code', title: '~/.codex/config.toml', code: `[mcp_servers.${name}]\nurl = "${url}"` },
        ],
    },
    {
        key: 'opencode',
        label: 'OpenCode',
        Icon: harnessMarkIcon('opencode'),
        blocks: (url, name) => [
            { kind: 'code', title: 'Terminal', code: 'opencode mcp add' },
            { kind: 'note', text: 'Choose Remote and paste the server URL when asked. Or add it to opencode.json directly:' },
            {
                kind: 'code',
                title: '~/.config/opencode/opencode.json',
                code: JSON.stringify({ mcp: { [name]: { type: 'remote', url, enabled: true } } }, null, 2),
            },
        ],
    },
    {
        key: 'openclaw',
        label: 'OpenClaw',
        Icon: harnessMarkIcon('openclaw'),
        blocks: (url, name) => [
            { kind: 'code', title: 'Terminal', code: `openclaw mcp add ${name} --url ${url}` },
            { kind: 'note', text: 'It probes the server before saving. Or add it to openclaw.json directly:' },
            {
                kind: 'code',
                title: '~/.openclaw/openclaw.json',
                code: JSON.stringify({ mcp: { servers: { [name]: { transport: 'streamable-http', url } } } }, null, 2),
            },
        ],
    },
    {
        key: 'hermes',
        label: 'Hermes',
        Icon: harnessMarkIcon('hermes'),
        blocks: (url, name) => [
            { kind: 'code', title: 'Terminal', code: `hermes mcp add ${name} --url ${url}` },
            { kind: 'note', text: 'Answer no when it asks if the server requires authentication (the link itself is the key). Or add it to your profile config directly:' },
            {
                kind: 'code',
                title: '~/.hermes/config.yaml',
                code: `mcp_servers:\n  ${name}:\n    url: "${url}"`,
            },
        ],
    },
    {
        key: 'cursor',
        label: 'Cursor',
        Icon: CursorMonoIcon,
        blocks: (url, name) => [
            { kind: 'link', label: 'Add to Cursor', href: cursorDeeplink(url, name), trailing: 'one-click install via deeplink' },
            { kind: 'note', text: 'Or add it manually to .cursor/mcp.json in your project (or ~/.cursor/mcp.json for all projects):' },
            {
                kind: 'code',
                title: '.cursor/mcp.json',
                code: JSON.stringify({ mcpServers: { [name]: { url } } }, null, 2),
            },
        ],
    },
    {
        key: 'vscode',
        label: 'VS Code',
        Icon: VSCodeIcon,
        blocks: (url, name) => [
            {
                kind: 'steps',
                steps: [
                    'CTRL/CMD + SHIFT + P and search for MCP: Add Server.',
                    'Select HTTP (HTTP or Server-Sent Events).',
                    `Paste the server URL and hit enter: ${url}`,
                    `Enter the name ${name} and hit enter.`,
                ],
            },
            { kind: 'note', text: 'Or add it to .vscode/mcp.json directly:' },
            {
                kind: 'code',
                title: '.vscode/mcp.json',
                code: JSON.stringify({ servers: { [name]: { type: 'http', url } } }, null, 2),
            },
        ],
    },
    {
        key: 'windsurf',
        label: 'Windsurf',
        Icon: WindsurfIcon,
        blocks: (url, name) => [
            {
                kind: 'steps',
                steps: [
                    'CTRL/CMD + , to open Windsurf settings.',
                    'Scroll to Cascade → MCP servers.',
                    'Select Add Server → Add custom server.',
                    'Enter the following configuration:',
                ],
            },
            {
                kind: 'code',
                title: 'mcp_config.json',
                code: JSON.stringify({ mcpServers: { [name]: { serverUrl: url } } }, null, 2),
            },
        ],
    },
    {
        key: 'zed',
        label: 'Zed',
        Icon: ZedIcon,
        blocks: (url, name) => [
            { kind: 'steps', steps: ['CMD + , to open Zed settings.', 'Add the server under context_servers:'] },
            {
                kind: 'code',
                title: 'settings.json',
                code: JSON.stringify(
                    { context_servers: { [name]: { source: 'custom', command: 'npx', args: ['-y', 'mcp-remote', url], env: {} } } },
                    null,
                    2,
                ),
            },
        ],
    },
    {
        key: 'other',
        label: 'Others',
        Icon: MCP as unknown as React.ComponentType<{ size?: number }>,
        blocks: (url, name) => [
            { kind: 'note', text: 'Any client that speaks Streamable HTTP just needs the URL — if a JSON config asks for a transport type, use "streamable-http".' },
            {
                kind: 'code',
                title: 'Standard config',
                code: JSON.stringify({ mcpServers: { [name]: { type: 'streamable-http', url } } }, null, 2),
            },
            { kind: 'note', text: 'Stdio-only clients can bridge through mcp-remote:' },
            { kind: 'code', title: 'mcp-remote bridge', code: `Command: npx\nArguments: -y mcp-remote ${url}\nEnvironment: none` },
        ],
    },
];

// QuickStep + MCP_QUICK_STEPS moved to ~/data/mcpQuickSteps (leaf module) so
// the edge-cached /agents pages can render the same snippets without this
// file's icon/socket deps; re-exported here so existing importers keep working.
export { MCP_QUICK_STEPS, type QuickStep } from '~/data/mcpQuickSteps';

/** Click-anywhere-to-copy code block. */
export function CopyBlock({ title, code }: { title: string; code: string }) {
    const [copied, setCopied] = useState(false);
    const copy = () => {
        navigator.clipboard.writeText(code);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
    };
    return (
        <div>
            <div className="mb-1 flex items-center justify-between gap-2">
                <span className="text-[10px] uppercase tracking-wider text-muted-foreground dark:text-zinc-500">{title}</span>
                <span className="flex items-center gap-1.5">
                    <span className={`inline-flex items-center gap-1 text-[11px] ${copied ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground dark:text-zinc-500'}`}>
                        {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                        {copied ? 'Copied' : 'Click to copy'}
                    </span>
                </span>
            </div>
            <button
                type="button"
                onClick={copy}
                title="Copy to clipboard"
                className="scrollbar-subtle block w-full cursor-pointer overflow-x-auto rounded-lg border border-border dark:border-white/[0.06] bg-muted dark:bg-black/40 px-3 py-2.5 text-left transition-colors hover:border-foreground/20 hover:bg-accent dark:hover:bg-black/60"
            >
                <pre className="text-[12px] leading-relaxed text-foreground">
                    <code>{code}</code>
                </pre>
            </button>
        </div>
    );
}

export function GuideBlockView({ block }: { block: GuideBlock }) {
    switch (block.kind) {
        case 'code':
            return <CopyBlock title={block.title} code={block.code} />;
        case 'note':
            return <p className="text-xs leading-relaxed text-muted-foreground">{block.text}</p>;
        case 'steps':
            return (
                <ol className="list-decimal space-y-1.5 pl-5 text-xs leading-relaxed text-foreground/80">
                    {block.steps.map(s => (
                        <li key={s}>{s}</li>
                    ))}
                </ol>
            );
        case 'link':
            return (
                <div className="flex items-center gap-2.5">
                    <a
                        href={block.href}
                        className="inline-flex items-center gap-1.5 rounded-md bg-foreground/[0.1] px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-foreground/[0.16]"
                    >
                        {block.label}
                    </a>
                    {block.trailing && <span className="text-[11px] text-muted-foreground dark:text-zinc-500">{block.trailing}</span>}
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
}

/** Generic per-client setup guide for the platform NoClick MCP server. */
export function MCPSetupModal({ open, onClose, url, urlError, serverName, title, intro }: MCPSetupModalProps) {
    const [activeIndex, setActiveIndex] = useState(0);
    const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
    const activeIndexRef = useRef(0);
    activeIndexRef.current = activeIndex;

    // Escape closes and ArrowUp/Down switch clients from ANYWHERE in the
    // modal (document capture — focus is often on a copy button or nowhere).
    useEffect(() => {
        if (!open) return;
        const onKey = (e: KeyboardEvent) => {
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
            <div className="fixed inset-0 z-[100] bg-black/60" onMouseDown={onClose} />
            <div
                role="dialog"
                aria-modal="true"
                aria-label={title}
                className="fixed left-1/2 top-[8vh] z-[101] w-[92vw] max-w-3xl -translate-x-1/2 overflow-hidden rounded-xl border border-border dark:border-white/10 bg-background dark:bg-[#0a0a0b] shadow-2xl dark:shadow-black/60"
            >
                <div className="border-b border-border dark:border-white/[0.06] px-4 py-3">
                    <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                        <Globe className="h-4 w-4 text-muted-foreground" />
                        {title}
                    </div>
                    <p className="mt-1 text-xs leading-relaxed text-muted-foreground dark:text-zinc-500">{intro}</p>
                </div>

                <div className="border-b border-border dark:border-white/[0.06] px-4 py-2.5">
                    {url ? (
                        <div className="space-y-2">
                            <CopyBlock title="Server URL" code={url} />
                        </div>
                    ) : urlError ? (
                        <div className="text-xs text-red-600 dark:text-red-400">{urlError}</div>
                    ) : (
                        <div className="flex items-center gap-2 text-xs text-muted-foreground dark:text-zinc-500">
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            Loading server URL…
                        </div>
                    )}
                </div>

                <div className="flex min-h-[300px]">
                    <div
                        role="tablist"
                        aria-orientation="vertical"
                        aria-label="MCP clients"
                        className="scrollbar-subtle w-44 shrink-0 space-y-0.5 overflow-y-auto border-r border-border dark:border-white/[0.06] p-2"
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
                                className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] transition-colors ${
                                    i === activeIndex
                                        ? 'bg-foreground/[0.1] text-foreground'
                                        : 'text-muted-foreground hover:bg-foreground/[0.04] hover:text-foreground'
                                }`}
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
                        className="scrollbar-subtle max-h-[46vh] flex-1 space-y-3 overflow-y-auto px-4 py-3"
                    >
                        {client.blocks(displayUrl, serverName).map((b, i) => (
                            <GuideBlockView key={i} block={b} />
                        ))}
                    </div>
                </div>

                <div className="flex items-center justify-between border-t border-border dark:border-white/[0.06] px-4 py-2.5">
                    <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                        <kbd className="rounded border border-border dark:border-white/[0.15] bg-foreground/[0.06] px-1.5 py-0.5 font-sans text-[10px] text-foreground/80">↑</kbd>
                        <kbd className="rounded border border-border dark:border-white/[0.15] bg-foreground/[0.06] px-1.5 py-0.5 font-sans text-[10px] text-foreground/80">↓</kbd>
                        switch client
                        <span className="px-1 text-muted-foreground/70 dark:text-zinc-600">·</span>
                        <kbd className="rounded border border-border dark:border-white/[0.15] bg-foreground/[0.06] px-1.5 py-0.5 font-sans text-[10px] text-foreground/80">esc</kbd>
                        close
                    </span>
                    <button
                        type="button"
                        onClick={onClose}
                        className="rounded-md bg-foreground/[0.08] px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-foreground/[0.12]"
                    >
                        Done
                    </button>
                </div>
            </div>
        </>,
        document.body,
    );
}

/** Platform surface: setup guides for the main NoClick MCP server (build and
 *  run workflows from any MCP client). Static URL; clients run the OAuth
 *  sign-in on first connect. Opened from the command palette. */
export function NoClickMCPSetupModal({ open, onClose }: { open: boolean; onClose: () => void }) {
    // The public MCP endpoint is the Cloudflare-proxied custom domain — NOT
    // VITE_API_URL, which some deployments use a separate backend socket URL for socket traffic.
    const url = mcpServerUrl();
    return (
        <MCPSetupModal
            open={open}
            onClose={onClose}
            url={url}
            serverName="noclick"
            title="Set up the NoClick MCP server"
            intro="Build, edit, and run your NoClick workflows from any MCP client. Your client will take you through a NoClick sign-in the first time it connects."
        />
    );
}
