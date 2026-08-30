/**
 * Shared credential-icon resolver. Settings → Credentials and the Debug
 * "Trigger Tests" tab both render a row per credential type and want the same
 * colored brand icon — building this map once and re-using it keeps the two
 * surfaces visually consistent.
 *
 * Resolution order:
 *  1. Special-case agent/MCP credential types that aren't tied to a workflow
 *     node schema (Codex, Claude Code, MCP servers, etc.).
 *  2. Walk AVAILABLE_NODES + NODE_SCHEMAS to find the workflow node whose
 *     schema declares this credential_type, and use its (colored) Icon.
 *  3. Fall back to the monochrome OAuth provider icon from oauthProviders.ts.
 *  4. Final fallback: a generic KeyRound icon.
 */

import { type ComponentType, type CSSProperties } from 'react';
import { Bot, KeyRound, Sparkles } from 'lucide-react';
import { Anthropic, MCP, OpenAI } from '@lobehub/icons';
import OpenRouter from '~/components/icons/OpenRouterIcon';
import GoogleIcon from '~/components/icons/GoogleIcon';
import MicrosoftIcon from '~/components/icons/MicrosoftIcon';
import { SiAtlassian, SiIntuit } from 'react-icons/si';
// Node brand icons come from the serialized node-icon singleton (dashboard loader),
// NOT the node registry — keeps this util (used by the always-mounted command
// palette + settings) off the registry's ~4.7MB node-component graph.
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';
import { HARNESS_BRANDS } from '~/lib/harnessBrand';
import { NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { OAUTH_PROVIDER_CONFIG, PROVIDER_ALIASES, getProviderConfigByCredentialType } from '~/utils/oauthProviders';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypes';
import { cn } from '~/lib/utils';

type IconCmp = ComponentType<{ className?: string; style?: CSSProperties }>;

// Wrap a pre-rendered icon HTML string (from the node-icon singleton) as an
// IconCmp so node-backed credential icons stay compatible with BrandIcon (which
// passes className + style); the child img/svg fills the sized wrapper.
function serializedIconComponent(html: string): IconCmp {
    return function NodeBrandIcon({ className, style }) {
        return (
            <span
                className={cn(
                    'inline-flex items-center justify-center [&>img]:w-full [&>img]:h-full [&>svg]:w-full [&>svg]:h-full',
                    className
                )}
                style={style}
                dangerouslySetInnerHTML={{ __html: html }}
            />
        );
    };
}
/** A resolved brand icon plus its brand color ('' = multicolor / leave untinted). */
type CredentialIconEntry = { Icon: IconCmp; iconColor: string };

// Lobehub icons accept `className` and render as SVGs sized via `width`/`height`,
// so Tailwind `w-N h-N` classes already do the right thing without a size prop.
const OpenAIIcon: IconCmp = OpenAI as unknown as IconCmp;
const AnthropicIcon: IconCmp = Anthropic as unknown as IconCmp;
const MCPIcon: IconCmp = MCP as unknown as IconCmp;
const OpenRouterIcon: IconCmp = OpenRouter as unknown as IconCmp;

// Wrap a public-SVG brand mark (served from /public/icons) as an IconCmp. Used
// for the CLI-harness agents whose marks aren't in @lobehub/icons.
function imgIconComponent(src: string, alt: string): IconCmp {
    return function ImgBrandIcon({ className, style }) {
        return <img src={src} alt={alt} className={cn('object-contain', className)} style={style} />;
    };
}

// Special credential types not tied to a node schema. Agent credentials are
// stored as `agent_<provider>` (agentCredentialModel.getAgentCredentialType), so
// each provider's brand mark is registered here — otherwise they fall through to
// the generic key. Rendered untinted (iconColor '' → white mark on the dark well),
// matching the existing agent_*_oauth entries. Harness marks source their svg
// path from the shared HARNESS_BRANDS registry so the paths don't drift. We use
// the @lobehub bare icons + public SVGs directly rather than importing
// PROVIDER_METADATA — that module eagerly builds ~50 icon elements at import and
// this file sits on the always-mounted command-palette path.
const SPECIAL_CREDENTIAL_ICONS: Record<string, IconCmp> = {
    agent_api_key: Sparkles,
    agent_openai: OpenAIIcon,
    agent_codex: OpenAIIcon,
    agent_codex_oauth: OpenAIIcon,
    agent_anthropic: AnthropicIcon,
    agent_claude_code: AnthropicIcon,
    agent_claude_code_oauth: AnthropicIcon,
    agent_openrouter: OpenRouterIcon,
    agent_opencode: imgIconComponent(HARNESS_BRANDS.opencode.markSrc, 'OpenCode'),
    agent_openclaw: imgIconComponent(HARNESS_BRANDS.openclaw.markSrc, 'OpenClaw'),
    agent_hermes_agent: imgIconComponent(HARNESS_BRANDS.hermes.markSrc, 'Hermes'),
    // SDK-created bot credentials occasionally surface with these raw schema
    // titles instead of a normalized credential_type — same intent, same icon.
    bot_token_credential: Bot,
    bottokencredential: Bot,
};

// For mcp_oauth credentials we try to surface the brand of the underlying MCP
// server (e.g. mcp.notion.com → Notion icon). Falls back to the generic MCP
// mark when nothing matches.
function resolveMcpIcon(serverUrl: string | undefined): IconCmp {
    if (!serverUrl) return MCPIcon;
    let hostname: string;
    try {
        hostname = new URL(serverUrl).hostname.toLowerCase();
    } catch {
        return MCPIcon;
    }
    // Pull the brand segment out of the hostname — e.g. `mcp.notion.com` → `notion`.
    const parts = hostname.split('.').filter(Boolean);
    const candidates = new Set<string>();
    if (parts.length >= 2) candidates.add(parts[parts.length - 2]);
    for (const part of parts) {
        if (part !== 'www' && part !== 'mcp' && part !== 'api') candidates.add(part);
    }
    for (const key of candidates) {
        const cfg = OAUTH_PROVIDER_CONFIG[key] ?? PROVIDER_ALIASES[key];
        if (cfg?.Icon) return cfg.Icon as IconCmp;
    }
    return MCPIcon;
}

// OAuth providers that power a FAMILY of nodes (Google, Microsoft, Atlassian,
// Intuit) own no node credential type of their own, and the provider config
// carries single-colour glyphs — a one-colour "G" is not the Google mark. The
// picker resolves these by provider key first. Single-colour brands are their
// own mark once tinted; Cal.com's reviewed asset already ships for its node.
const OAUTH_PROVIDER_BRAND_ICONS: Record<string, CredentialIconEntry> = {
    google: { Icon: GoogleIcon, iconColor: '' },
    microsoft: { Icon: MicrosoftIcon, iconColor: '' },
    atlassian: { Icon: SiAtlassian as unknown as IconCmp, iconColor: '#0052CC' },
    intuit: { Icon: SiIntuit as unknown as IconCmp, iconColor: '#236CFF' },
    calcom: { Icon: imgIconComponent('/icons/cal-com.svg', 'Cal.com'), iconColor: '' },
    discord: { Icon: OAUTH_PROVIDER_CONFIG.discord.Icon as IconCmp, iconColor: '#5865F2' },
};

let _iconCache: Map<string, CredentialIconEntry> | null = null;

function buildCredentialIconMap(): Map<string, CredentialIconEntry> {
    if (_iconCache) return _iconCache;
    _iconCache = new Map();
    // Walk the node JSON schemas (data) for credential types; resolve the owning
    // node's brand icon from the serialized icon singleton (not the registry).
    for (const nodeType of Object.keys(NODE_SCHEMAS)) {
        const schema = NODE_SCHEMAS[nodeType];
        if (!schema?.$defs) continue;
        const credProp = schema.properties?.credentials;
        if (!credProp) continue;
        const refs: string[] = [];
        if (credProp.$ref) refs.push(credProp.$ref.split('/').pop()!);
        if (credProp.anyOf) {
            for (const entry of credProp.anyOf) {
                if (entry.$ref) refs.push(entry.$ref.split('/').pop()!);
            }
        }
        const iconMeta = getNodeIconMeta(nodeType);
        if (!iconMeta?.iconHtml) continue;
        for (const title of refs) {
            const defn = schema.$defs[title];
            if (!defn) continue;
            const constVal = defn.properties?.credential_type?.const;
            // Index under the canonical const AND the lowercased raw schema title
            // (getCredentialTypeFromSchemaTitle returns the mapped type or the
            // lowercased title). The latter lets legacy SDK-created credentials
            // that stored the raw title verbatim — e.g.
            // `instagrampageaccesstokencredential` — still resolve to the node icon.
            const keys = new Set<string>([getCredentialTypeFromSchemaTitle(title), title.toLowerCase()]);
            if (constVal) keys.add(constVal);
            let entry: CredentialIconEntry | null = null;
            for (const key of keys) {
                if (!key || _iconCache.has(key)) continue;
                if (!entry) {
                    entry = {
                        Icon: serializedIconComponent(iconMeta.iconHtml),
                        iconColor: iconMeta.iconColor,
                    };
                }
                _iconCache.set(key, entry);
            }
        }
    }
    return _iconCache;
}

export function getCredentialIcon(
    credentialType: string,
    metadata?: Record<string, unknown> | null,
): { Icon: IconCmp; iconColor: string; hasServiceIcon: boolean } {
    // mcp / special (agent, OpenAI, Anthropic) marks are monochrome or
    // hardcoded-fill and look right untinted, so iconColor is ''.
    if (credentialType === 'mcp_oauth' || credentialType === 'mcp_api_key') {
        const serverUrl = typeof metadata?.server_url === 'string' ? metadata.server_url : undefined;
        return { Icon: resolveMcpIcon(serverUrl), iconColor: '', hasServiceIcon: true };
    }
    const special = SPECIAL_CREDENTIAL_ICONS[credentialType];
    if (special) return { Icon: special, iconColor: '', hasServiceIcon: true };

    // Node-backed credential → carry the node's brand color (matches the canvas).
    const nodeEntry = buildCredentialIconMap().get(credentialType);
    if (nodeEntry) return { ...nodeEntry, hasServiceIcon: true };
    const config = getProviderConfigByCredentialType(credentialType);
    if (config?.Icon) return { Icon: config.Icon, iconColor: config.iconColor ?? '', hasServiceIcon: true };
    return { Icon: KeyRound, iconColor: '', hasServiceIcon: false };
}

/** The mark for an OAuth provider KEY (the setup map's / provider config's key),
 *  as opposed to a stored credential's type: family providers have no
 *  `<provider>_oauth` credential, so a type-based lookup lands on the key. */
export function getOAuthProviderIcon(provider: string): { Icon: IconCmp; iconColor: string; hasServiceIcon: boolean } {
    const brand = OAUTH_PROVIDER_BRAND_ICONS[provider];
    if (brand) return { ...brand, hasServiceIcon: true };
    const nodeEntry = buildCredentialIconMap().get(`${provider}_oauth`);
    if (nodeEntry) return { ...nodeEntry, hasServiceIcon: true };
    const config = OAUTH_PROVIDER_CONFIG[provider] ?? PROVIDER_ALIASES[provider];
    if (config?.Icon) return { Icon: config.Icon as IconCmp, iconColor: config.iconColor ?? '', hasServiceIcon: true };
    return { Icon: KeyRound, iconColor: '', hasServiceIcon: false };
}
