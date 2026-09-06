// The minimal per-client MCP connect path (ONE method each — the easiest
// current one), extracted from MCPConnectModal so weight-free surfaces (the
// edge-cached /agents SEO pages) can use the same snippets without pulling the
// modal's icon/socket deps into their bundle. MCPConnectModal re-exports these,
// so the modal, the Setup finale, and the marketing pages share one source.

export interface QuickStep {
    text: string;
    code?: string;
    /** Render `code` as a terminal command ($-prefixed prompt styling). */
    terminal?: boolean;
    link?: { label: string; href: string };
}

// btoa alone throws on non-Latin1 input; encode through UTF-8 bytes so any
// label/url survives.
function b64utf8(s: string) {
    return btoa(String.fromCharCode(...new TextEncoder().encode(s)));
}

export const cursorDeeplink = (url: string, name: string) =>
    `cursor://anysphere.cursor-deeplink/mcp/install?name=${encodeURIComponent(
        name
    )}&config=${b64utf8(JSON.stringify({ url }))}`;

/** The finale's minimal numbered connect path per client — ONE method each,
    the easiest current one (one-command adds where the client has them;
    verified Aug 2026). The modal keeps the fuller alternatives. */
export const MCP_QUICK_STEPS: Record<
    string,
    (url: string, name: string) => QuickStep[]
> = {
    'claude-code': (url, name) => [
        {
            text: 'Run this in your terminal',
            code: `claude mcp add --transport http ${name} ${url}`,
            terminal: true,
        },
    ],
    codex: (url, name) => [
        {
            text: 'Run this in your terminal',
            code: `codex mcp add ${name} --url ${url}`,
            terminal: true,
        },
    ],
    opencode: (url) => [
        {
            text: 'Run this in your terminal',
            code: 'opencode mcp add',
            terminal: true,
        },
        { text: 'Choose Remote and paste your server URL', code: url },
        {
            text: 'Choose No when asked about OAuth authentication — the link itself is the key',
        },
    ],
    claude: (url) => [
        { text: 'In Claude, open Settings → Connectors' },
        { text: 'Add custom connector and paste your server URL', code: url },
    ],
    chatgpt: (url) => [
        {
            text: 'Turn on Developer mode in Settings → Apps & Connectors → Advanced',
        },
        { text: 'Create a connector and paste your server URL', code: url },
    ],
    cursor: (url, name) => [
        {
            text: 'Install with one click',
            link: { label: 'Add to Cursor', href: cursorDeeplink(url, name) },
        },
        { text: 'Approve the server when Cursor asks' },
    ],
    vscode: (url, name) => [
        {
            text: 'Run this in your terminal',
            code: `code --add-mcp '${JSON.stringify({ name, type: 'http', url })}'`,
            terminal: true,
        },
    ],
    openclaw: (url, name) => [
        {
            text: 'Run this in your terminal',
            code: `openclaw mcp add ${name} --url ${url}`,
            terminal: true,
        },
    ],
    hermes: (url, name) => [
        {
            text: 'Run this in your terminal',
            code: `hermes mcp add ${name} --url ${url}`,
            terminal: true,
        },
        {
            text: 'Answer no when asked if the server requires authentication — the link itself is the key',
        },
    ],
    other: (url, name) => [
        {
            text: "Add your server to the agent's MCP config",
            code: JSON.stringify(
                { mcpServers: { [name]: { type: 'streamable-http', url } } },
                null,
                2
            ),
        },
    ],
};

/** What makes a client actually handshake once the config is saved, and how
    to check from the client's side. Every connect surface renders this under
    its status: a hosted link only sees a client when the client STARTS a
    session, and "waiting for it to connect" alone never said so — a visitor
    ran `opencode mcp add` (which only writes the config), watched the finale
    for four minutes, left, and OpenCode connected 84s later (2026-09-05).
    Keyed by MCP_CLIENT_GUIDES key; verified against client docs 2026-09. */
export interface ConnectHint {
    /** One sentence naming the action that triggers the handshake. */
    trigger: string;
    /** A client-side check. Terminal checks that list servers also perform
        the handshake, so running one lights the status up. */
    check?: QuickStep;
}

const LISTS_AND_CONNECTS = 'Check from your side — this also connects it';

export const MCP_CONNECT_HINTS: Record<string, ConnectHint> = {
    'claude-code': {
        trigger:
            'Claude Code connects when a session starts — run claude, or restart a running one.',
        check: { text: LISTS_AND_CONNECTS, code: 'claude mcp list', terminal: true },
    },
    codex: {
        trigger:
            'Codex connects when a session starts — run codex, or restart a running one.',
        check: { text: 'Inside Codex, type /mcp to see the server and its tools' },
    },
    opencode: {
        trigger:
            'opencode mcp add only saves the config. OpenCode connects when it starts — run opencode, or restart a running one.',
        check: { text: LISTS_AND_CONNECTS, code: 'opencode mcp list', terminal: true },
    },
    openclaw: {
        trigger:
            'OpenClaw probes the server while adding it, so this lights up during openclaw mcp add.',
    },
    hermes: {
        trigger: 'Hermes connects when it next starts a session.',
    },
    claude: {
        trigger: 'claude.ai connects as soon as you click Add.',
        check: { text: 'Turn it on in a chat: + → Connectors → toggle it on' },
    },
    chatgpt: {
        trigger: 'ChatGPT connects when you create the connector.',
        check: { text: 'Enable it from the + / tools menu in a new chat' },
    },
    cursor: {
        trigger: 'Cursor connects as soon as you approve the install.',
        check: {
            text: 'Cursor Settings → MCP shows a green dot and the tool list once it is live',
        },
    },
    vscode: {
        trigger: 'VS Code starts the server the first time agent chat needs it.',
        check: {
            text: 'To start it now: Command Palette → MCP: List Servers → pick it → Start',
        },
    },
    windsurf: {
        trigger:
            'Windsurf connects when you save the config and refresh the MCP servers list.',
    },
    zed: {
        trigger: 'Zed connects when you save settings.json.',
        check: {
            text: 'Settings → AI → MCP Servers shows a green dot ("Server is active") once it is live',
        },
    },
    other: {
        trigger:
            'Most clients connect when they start — restart yours after saving the config.',
    },
};

export function connectHintFor(clientKey: string): ConnectHint {
    return MCP_CONNECT_HINTS[clientKey] ?? MCP_CONNECT_HINTS.other;
}
