// Every MCP client NoClick tells people how to connect, one entry each: its quick path (ONE method, the easiest
// current one: a one-command add where the client has it), its full guide (alternatives, config files) and what
// makes it actually connect. The one source for the connect modal, the Setup finale, the coordinator's setup card,
// the /agents pages and the platform docs' "Connect a client" section (cloud/docs/mcpClients.ts), which the
// coordinator's search reads. A leaf module (no icons, no socket) so edge-cached pages can use it; the modal adds
// each client's icon. Snippets verified against each client's own docs (2026-09; Codex app 2026-10): key names
// diverge (url vs serverUrl vs TOML), so keep them in sync when a client's docs move.

export interface QuickStep {
    text: string;
    code?: string;
    /** Render `code` as a terminal command ($-prefixed prompt styling). */
    terminal?: boolean;
    link?: { label: string; href: string };
}

export type GuideBlock =
    | { kind: 'code'; title: string; code: string }
    | { kind: 'steps'; title?: string; steps: string[] }
    | { kind: 'link'; label: string; href: string; trailing?: string }
    | { kind: 'note'; text: string };

/** What makes a client actually handshake once the config is saved, and how to check from the client's side. Every
    connect surface renders this under its status: a hosted link only sees a client when the client STARTS a
    session, and "waiting for it to connect" alone never said so: a visitor ran `opencode mcp add` (which only
    writes the config), watched the finale for four minutes, left, and OpenCode connected 84s later (2026-09-05). */
export interface ConnectHint {
    /** One sentence naming the action that triggers the handshake. */
    trigger: string;
    /** A client-side check. Terminal checks that list servers also perform the handshake, so running one lights
        the status up. */
    check?: QuickStep;
}

export interface McpClient {
    key: string;
    label: string;
    quick: (url: string, name: string) => QuickStep[];
    guide: (url: string, name: string) => GuideBlock[];
    hint: ConnectHint;
}

// btoa alone throws on non-Latin1 input; encode through UTF-8 bytes so any label/url survives.
function b64utf8(s: string) {
    return btoa(String.fromCharCode(...new TextEncoder().encode(s)));
}

export const cursorDeeplink = (url: string, name: string) =>
    `cursor://anysphere.cursor-deeplink/mcp/install?name=${encodeURIComponent(name)}&config=${b64utf8(JSON.stringify({ url }))}`;

const json = (value: unknown) => JSON.stringify(value, null, 2);
const terminal = (
    code: string,
    text = 'Run this in your terminal'
): QuickStep => ({ text, code, terminal: true });

const LISTS_AND_CONNECTS = 'Check from your side — this also connects it';
const NO_AUTH = 'the link itself is the key';

// Each client's one command or config, used by both its quick path and its guide.
const claudeCodeAdd = (url: string, name: string) =>
    `claude mcp add --transport http ${name} ${url}`;
const codexAdd = (url: string, name: string) =>
    `codex mcp add ${name} --url ${url}`;
const openclawAdd = (url: string, name: string) =>
    `openclaw mcp add ${name} --url ${url}`;
const hermesAdd = (url: string, name: string) =>
    `hermes mcp add ${name} --url ${url}`;
const vscodeAdd = (url: string, name: string) =>
    `code --add-mcp '${JSON.stringify({ name, type: 'http', url })}'`;
const windsurfConfig = (url: string, name: string) =>
    json({ mcpServers: { [name]: { serverUrl: url } } });
const zedConfig = (url: string, name: string) =>
    json({ context_servers: { [name]: { url } } });
const standardConfig = (url: string, name: string) =>
    json({ mcpServers: { [name]: { type: 'streamable-http', url } } });

export const MCP_CLIENTS: McpClient[] = [
    {
        key: 'claude',
        label: 'Claude',
        quick: (url) => [
            { text: 'In Claude, open Settings → Connectors' },
            {
                text: 'Add custom connector and paste your server URL',
                code: url,
            },
        ],
        guide: (url) => [
            {
                kind: 'note',
                text: 'Works on claude.ai, the Claude desktop app and mobile through custom connectors — Free (one connector), Pro, Max, Team and Enterprise.',
            },
            {
                kind: 'steps',
                steps: [
                    'Open Customize → Connectors (on Team and Enterprise an Owner adds it under Organization settings → Connectors first).',
                    'Click + and choose Add custom connector.',
                    'Paste the server URL and click Add.',
                    'In a chat, click + → Connectors and turn it on.',
                ],
            },
            { kind: 'code', title: 'Server URL', code: url },
        ],
        hint: {
            trigger: 'claude.ai connects as soon as you click Add.',
            check: {
                text: 'Turn it on in a chat: + → Connectors → toggle it on',
            },
        },
    },
    {
        key: 'claude-code',
        label: 'Claude Code',
        quick: (url, name) => [terminal(claudeCodeAdd(url, name))],
        guide: (url, name) => [
            { kind: 'code', title: 'Terminal', code: claudeCodeAdd(url, name) },
            {
                kind: 'note',
                text: 'Verify with claude mcp list (it connects and shows ✔ Connected) or /mcp inside a session. To share it with your team instead, add it to .mcp.json in the project root:',
            },
            {
                kind: 'code',
                title: '.mcp.json',
                code: json({ mcpServers: { [name]: { type: 'http', url } } }),
            },
        ],
        hint: {
            trigger:
                'Claude Code connects when a session starts — run claude, or restart a running one.',
            check: {
                text: LISTS_AND_CONNECTS,
                code: 'claude mcp list',
                terminal: true,
            },
        },
    },
    {
        key: 'chatgpt',
        label: 'ChatGPT',
        quick: (url) => [
            {
                text: 'Turn on Developer mode in Settings → Apps & Connectors → Advanced',
            },
            { text: 'Create a connector and paste your server URL', code: url },
        ],
        guide: (url) => [
            {
                kind: 'note',
                text: 'Custom MCP connectors need developer mode (Plus, Pro, Business, Enterprise and Edu — set up on the web app; on team plans an admin must allow it first).',
            },
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
        hint: {
            trigger: 'ChatGPT connects when you create the connector.',
            check: { text: 'Enable it from the + / tools menu in a new chat' },
        },
    },
    {
        key: 'codex',
        label: 'Codex',
        // The Codex app, the CLI and the IDE extension share one config, so the one command adds it to all three.
        quick: (url, name) => [
            terminal(
                codexAdd(url, name),
                'Run this in your terminal. The Codex app shares its config, so it gets the server too'
            ),
        ],
        guide: (url, name) => [
            { kind: 'code', title: 'Terminal', code: codexAdd(url, name) },
            {
                kind: 'note',
                text: 'The Codex app, the CLI and the IDE extension share this config. In the app you can add it instead under Settings → MCP servers → Add server: choose Streamable HTTP, paste the server URL, save, then Restart. Verify with codex mcp list, or /mcp inside a Codex session. Or configure it directly:',
            },
            {
                kind: 'code',
                title: '~/.codex/config.toml',
                code: `[mcp_servers.${name}]\nurl = "${url}"`,
            },
        ],
        hint: {
            trigger:
                'Codex connects when a session starts — run codex, or restart a running one (in the Codex app, Restart).',
            check: {
                text: 'Inside Codex, type /mcp to see the server and its tools',
            },
        },
    },
    {
        key: 'opencode',
        label: 'OpenCode',
        quick: (url) => [
            terminal('opencode mcp add'),
            { text: 'Choose Remote and paste your server URL', code: url },
            {
                text: `Choose No when asked about OAuth authentication — ${NO_AUTH}`,
            },
        ],
        guide: (url, name) => [
            { kind: 'code', title: 'Terminal', code: 'opencode mcp add' },
            {
                kind: 'note',
                text: `Choose Remote, paste the server URL, and answer No to OAuth — ${NO_AUTH}. This only saves the config: OpenCode connects when it starts, and opencode mcp list checks (and connects) from your side. Or add it to opencode.json directly:`,
            },
            {
                kind: 'code',
                title: '~/.config/opencode/opencode.json',
                code: json({
                    mcp: { [name]: { type: 'remote', url, enabled: true } },
                }),
            },
        ],
        hint: {
            trigger:
                'opencode mcp add only saves the config. OpenCode connects when it starts — run opencode, or restart a running one.',
            check: {
                text: LISTS_AND_CONNECTS,
                code: 'opencode mcp list',
                terminal: true,
            },
        },
    },
    {
        key: 'openclaw',
        label: 'OpenClaw',
        quick: (url, name) => [terminal(openclawAdd(url, name))],
        guide: (url, name) => [
            { kind: 'code', title: 'Terminal', code: openclawAdd(url, name) },
            {
                kind: 'note',
                text: 'It probes the server before saving. Or add it to openclaw.json directly:',
            },
            {
                kind: 'code',
                title: '~/.openclaw/openclaw.json',
                code: json({
                    mcp: {
                        servers: {
                            [name]: { transport: 'streamable-http', url },
                        },
                    },
                }),
            },
        ],
        hint: {
            trigger:
                'OpenClaw probes the server while adding it, so this lights up during openclaw mcp add.',
        },
    },
    {
        key: 'hermes',
        label: 'Hermes',
        quick: (url, name) => [
            terminal(hermesAdd(url, name)),
            {
                text: `Answer no when asked if the server requires authentication — ${NO_AUTH}`,
            },
        ],
        guide: (url, name) => [
            { kind: 'code', title: 'Terminal', code: hermesAdd(url, name) },
            {
                kind: 'note',
                text: `Answer no when it asks if the server requires authentication (${NO_AUTH}). Or add it to your profile config directly:`,
            },
            {
                kind: 'code',
                title: '~/.hermes/config.yaml',
                code: `mcp_servers:\n  ${name}:\n    url: "${url}"`,
            },
        ],
        hint: { trigger: 'Hermes connects when it next starts a session.' },
    },
    {
        key: 'cursor',
        label: 'Cursor',
        quick: (url, name) => [
            {
                text: 'Install with one click',
                link: {
                    label: 'Add to Cursor',
                    href: cursorDeeplink(url, name),
                },
            },
            { text: 'Approve the server when Cursor asks' },
        ],
        guide: (url, name) => [
            {
                kind: 'link',
                label: 'Add to Cursor',
                href: cursorDeeplink(url, name),
                trailing: 'one-click install via deeplink',
            },
            {
                kind: 'note',
                text: 'Or add it manually to .cursor/mcp.json in your project (or ~/.cursor/mcp.json for all projects):',
            },
            {
                kind: 'code',
                title: '.cursor/mcp.json',
                code: json({ mcpServers: { [name]: { url } } }),
            },
            {
                kind: 'note',
                text: 'Cursor Settings → MCP shows a green dot and the tool list once it is live.',
            },
        ],
        hint: {
            trigger: 'Cursor connects as soon as you approve the install.',
            check: {
                text: 'Cursor Settings → MCP shows a green dot and the tool list once it is live',
            },
        },
    },
    {
        key: 'vscode',
        label: 'VS Code',
        quick: (url, name) => [terminal(vscodeAdd(url, name))],
        guide: (url, name) => [
            { kind: 'code', title: 'Terminal', code: vscodeAdd(url, name) },
            { kind: 'note', text: 'Or from the Command Palette:' },
            {
                kind: 'steps',
                steps: [
                    'CTRL/CMD + SHIFT + P and search for MCP: Add Server.',
                    'Select HTTP (HTTP or Server-Sent Events).',
                    `Paste the server URL and hit enter: ${url}`,
                    `Enter the name ${name} and hit enter.`,
                ],
            },
            {
                kind: 'note',
                text: 'Or add it to .vscode/mcp.json directly. MCP: List Servers shows it and can start it right away:',
            },
            {
                kind: 'code',
                title: '.vscode/mcp.json',
                code: json({ servers: { [name]: { type: 'http', url } } }),
            },
        ],
        hint: {
            trigger:
                'VS Code starts the server the first time agent chat needs it.',
            check: {
                text: 'To start it now: Command Palette → MCP: List Servers → pick it → Start',
            },
        },
    },
    {
        key: 'windsurf',
        label: 'Windsurf',
        quick: (url, name) => [
            {
                text: 'In Windsurf Settings → Cascade → MCP Servers, add a custom server with this config',
                code: windsurfConfig(url, name),
            },
            { text: 'Save, then refresh the servers list' },
        ],
        guide: (url, name) => [
            {
                kind: 'steps',
                steps: [
                    'Open Windsurf Settings → Cascade → MCP Servers (or the MCPs icon in the Cascade panel).',
                    'Select Add custom server and enter the configuration below.',
                    'Save, then refresh the servers list.',
                ],
            },
            {
                kind: 'code',
                title: '~/.codeium/windsurf/mcp_config.json',
                code: windsurfConfig(url, name),
            },
        ],
        hint: {
            trigger:
                'Windsurf connects when you save the config and refresh the MCP servers list.',
        },
    },
    {
        key: 'zed',
        label: 'Zed',
        quick: (url, name) => [
            {
                text: 'Open Zed settings (CMD + ,) and add the server under context_servers',
                code: zedConfig(url, name),
            },
        ],
        guide: (url, name) => [
            {
                kind: 'steps',
                steps: [
                    'CMD + , to open Zed settings.',
                    'Add the server under context_servers:',
                ],
            },
            {
                kind: 'code',
                title: 'settings.json',
                code: zedConfig(url, name),
            },
            {
                kind: 'note',
                text: 'Settings → AI → MCP Servers shows a green dot ("Server is active") once it connects. Older Zed builds without remote support can bridge through mcp-remote:',
            },
            {
                kind: 'code',
                title: 'settings.json (legacy bridge)',
                code: json({
                    context_servers: {
                        [name]: {
                            source: 'custom',
                            command: 'npx',
                            args: ['-y', 'mcp-remote', url],
                            env: {},
                        },
                    },
                }),
            },
        ],
        hint: {
            trigger: 'Zed connects when you save settings.json.',
            check: {
                text: 'Settings → AI → MCP Servers shows a green dot ("Server is active") once it is live',
            },
        },
    },
    {
        key: 'other',
        label: 'Others',
        quick: (url, name) => [
            {
                text: "Add your server to the agent's MCP config",
                code: standardConfig(url, name),
            },
        ],
        guide: (url, name) => [
            {
                kind: 'note',
                text: 'Any client that speaks Streamable HTTP just needs the URL — if a JSON config asks for a transport type, use "streamable-http".',
            },
            {
                kind: 'code',
                title: 'Standard config',
                code: standardConfig(url, name),
            },
            {
                kind: 'note',
                text: 'Stdio-only clients can bridge through mcp-remote:',
            },
            {
                kind: 'code',
                title: 'mcp-remote bridge',
                code: `Command: npx\nArguments: -y mcp-remote ${url}\nEnvironment: none`,
            },
        ],
        hint: {
            trigger:
                'Most clients connect when they start — restart yours after saving the config.',
        },
    },
];

const OTHER = MCP_CLIENTS[MCP_CLIENTS.length - 1];

export const MCP_QUICK_STEPS: Record<string, McpClient['quick']> =
    Object.fromEntries(MCP_CLIENTS.map((c) => [c.key, c.quick]));

export const MCP_CONNECT_HINTS: Record<string, ConnectHint> =
    Object.fromEntries(MCP_CLIENTS.map((c) => [c.key, c.hint]));

export function connectHintFor(clientKey: string): ConnectHint {
    return MCP_CONNECT_HINTS[clientKey] ?? OTHER.hint;
}

const plain = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, '');

/** The client a person names in what they wrote ("connect my claude code to reddit"): the longest name found wins, so
 *  Claude Code isn't read as Claude; undefined when they name none NoClick has steps for. */
export function mcpClientNamedIn(text: string | null | undefined): McpClient | undefined {
    if (!text) return undefined;
    const said = ` ${text.toLowerCase().replace(/[^a-z0-9]+/g, ' ')} `;
    const named = MCP_CLIENTS.filter((c) => c !== OTHER && [c.label, c.key].some((n) => said.includes(` ${n.toLowerCase().replace(/[^a-z0-9]+/g, ' ')} `)));
    return named.sort((a, b) => b.label.length - a.label.length)[0];
}

/** The client a key or a name says (`codex`, `Claude Code`, `claude_code`); undefined for one NoClick has no steps for. */
export function mcpClientFor(
    keyOrName: string | null | undefined
): McpClient | undefined {
    if (!keyOrName) return undefined;
    const wanted = plain(keyOrName);
    return MCP_CLIENTS.find(
        (c) => plain(c.key) === wanted || plain(c.label) === wanted
    );
}
