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
