// Work's slots: the places in it a host may fill (src/slots.ts), each with what stands there otherwise. An app's or an
// account's mark is the shared `connection.mark`, and connecting an app's account or an AI account the shared
// `connect.app` and `connect.model` (src/ui/slots.ts); an agent's face and the pickers' agents from
// elsewhere are the channels layer's (screens/channels/slots.ts); the cards under an agent's turns are the chat's
// (screens/chat/slots.ts).
import type { ComponentType } from 'react';
import type { HarnessName, NoClick } from 'noclick';
import { slot } from '@/slots';
import type { ConnectableApp } from '@/ui/slots';
import { StandardMarkdown } from '@/screens/resources/slotStandards';
import type { PreviewParts } from '@/screens/resources/FilePreview';
import { sdkTyping } from '@/screens/channels/sdkTransport';
import type { SendTyping } from '@/screens/channels/typing';
import {
    FundsOnNoClick,
    LinkedFileCard,
    useNoToolServerSignIn,
    useV1ToolApps,
    workAddress,
    workspacePreviewParts,
} from './slotStandards';

// ── an agent's turns ───────────────────────────────────────────────────────

export interface MarkdownProps {
    content: string;
    className?: string;
    /** A single line break is a break, as in a chat message. */
    breaks?: boolean;
}

/** A reply's, a question's or a browser's found text, drawn from its Markdown. The standard draws it as a code
 *  repository's README is. */
export const REPLY_MARKDOWN = slot<ComponentType<MarkdownProps>>('work.reply.markdown', StandardMarkdown);

/** A file a texted or emailed message carried, or one an agent made, as a card in the message (its type and size
 *  where they're known). The standard is a link that opens it. */
export const MESSAGE_FILE = slot<ComponentType<{ name: string; url: string; mimeType?: string; sizeBytes?: number }>>('work.message.file', LinkedFileCard);

/** A model's name as people read it, by its id (`anthropic/claude-sonnet-5-5`); undefined where the host knows none. */
export const MODEL_NAME = slot<(model: string) => string | undefined>('work.model.name', () => undefined);

// ── connecting ──────────────────────────────────────────────────────────────

/** An app an agent can use as tools: one whose account is connected through the shared `connect.app` slot
 *  (`@/ui/slots`), as connecting an AI account a model needs is through `connect.model`. */
export type ToolApp = ConnectableApp;

export interface WorkApps {
    /** The apps an agent can use as tools, read once and kept. */
    useToolApps(): ToolApp[];
    /** The app an account of `credentialType` is with, where it acts through an app named otherwise (GitHub's through
     *  `automation-github-rest`); undefined where the host can't tell. */
    serviceOf(credentialType: string): { value: string; label: string } | undefined;
}

/** What Work knows of apps: which an agent can use as tools, and whose an account is. The standard reads the
 *  integrations the platform API lists and knows no account's app beyond its own name. */
export const APPS = slot<WorkApps>('work.apps', { useToolApps: useV1ToolApps, serviceOf: () => undefined });

/** The team workspace the page shows (its organization's id), in which the accounts a message points at are read and
 *  used: one a teammate shared with that team is the team's, there alone. The standard is none: the account's own. */
export const TEAM_WORKSPACE = slot<() => string | null>('work.teamWorkspace', () => null);

/** Signing in to a tool server (an MCP server) added as an agent's tool, or carried by a move. */
export interface ToolServerSignIn {
    /** Ask the server how it signs in. */
    discover: (url: string) => Promise<unknown>;
    /** Sign in; the credential that lands goes to `onCredentialCreated`. */
    connect: (url: string, name: string) => Promise<unknown>;
    /** What the server said of signing in, once asked. */
    discoveryResult: { requires_oauth: boolean } | null;
    isDiscovering: boolean;
    isConnecting: boolean;
    error: string | null;
}

/** How a tool server that asks to sign in is signed in to. The standard can't sign in here: it says to add the server
 *  on NoClick, or give its key. */
export const TOOL_SERVER_SIGN_IN = slot<(options: { onCredentialCreated: (credentialId: string) => void }) => ToolServerSignIn>('work.toolServer.signIn', useNoToolServerSignIn);

export interface AddFundsProps {
    isOpen: boolean;
    /** The costly model it's opened for, saying why it needs funds you add; null for plain Add funds. */
    forModel: CostlyModel | null;
    /** The change it was opened for is made once the funds land. */
    switching: boolean;
    onOpenChange: (open: boolean) => void;
}

/** A model whose output costs more than NoClick lets its key run without funds the account added. */
export interface CostlyModel {
    name: string;
    outputUsdPerMillion: number | null;
    needsUsd: number;
}

/** Adding funds to the account, where a costly model needs them. The standard links to NoClick's own page for it. */
export const ADD_FUNDS = slot<ComponentType<AddFundsProps>>('work.funds.add', FundsOnNoClick);

// ── drawing ─────────────────────────────────────────────────────────────────

/** A coding harness's mark the app has no drawing of (OpenCode's, Hermes', OpenClaw's): an image, drawn small. */
export interface HarnessArt {
    src: string;
    /** White art for dark backgrounds, inverted in a light theme. */
    monochrome?: boolean;
    /** How much it's scaled inside its box, for art whose own fit reads too large or small. */
    inset?: number;
}

/** The marks of the coding harnesses the app has no drawing of, by harness; one without is a plain dot. Nothing
 *  stands there. */
export const HARNESS_MARK = slot<Partial<Record<HarnessName, HarnessArt>>>('work.harness.mark', {});

/** How an agent's workspace files preview: their bodies at their signed links, and where they download from. The
 *  standard shows a picture, a recording or text at the link the platform API signed. */
export const FILE_PREVIEW = slot<PreviewParts>('work.file.preview', workspacePreviewParts);

// ── where Work is ──────────────────────────────────────────────────────────

export interface WorkAddress {
    /** An address for a place in Work, given as Work's own params. */
    href: (place: URLSearchParams) => string;
    /** Goes there, closing whatever else Work had open. */
    go: (place: URLSearchParams) => void;
}

/** Where Work is, for its pieces drawn elsewhere (a card, Resources) to open a place in it. The standard is the app's
 *  own `/work`. */
export const WORK_ADDRESS = slot<WorkAddress>('work.address', workAddress('/work'));

/** How you're said to be typing in a space you joined in another account, through its session's client. The standard
 *  says it through the platform API, as in your own spaces. */
export const JOINED_TYPING = slot<(client: NoClick) => SendTyping>('work.joinedSpace.typing', sdkTyping);
