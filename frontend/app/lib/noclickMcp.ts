// The MCP server the app's setup guides name (Connect, the command palette, Connections): by default this backend's own
// /mcp; a deployment with a server of its own registers it.
import { mcpServerUrl } from '~/lib/hostedDefaults';

export interface NoClickMcp {
    url: string;
    /** One line under the setup guide's title: what a client can do there. */
    intro: string;
}

let registered: NoClickMcp | null = null;

export function registerNoClickMcp(mcp: NoClickMcp) {
    registered = mcp;
}

export function noclickMcp(): NoClickMcp {
    return registered ?? { url: mcpServerUrl(), intro: 'Build and run your automations from Claude, ChatGPT, Cursor and other MCP clients.' };
}
