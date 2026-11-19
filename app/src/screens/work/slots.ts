// Work's slots: the places in it a host may fill (src/slots.ts), each with what stands there otherwise. An app's or an
// account's mark is the shared `connection.mark` (src/ui/slots.ts); an agent's face and the pickers' agents from
// elsewhere are the channels layer's (screens/channels/slots.ts).
import type { ComponentType, ReactNode } from 'react';
import type { HarnessName, NoClick } from 'noclick';
import { slot } from '@/slots';
import type { ThreadJobs } from '@/lib/threadJobs';
import type { BrandIconComponent } from '@/ui/BrandIcon';
import type { Thread, TurnEntry } from '@/lib/agentThread/thread';
import { StandardMarkdown } from '@/screens/resources/slotStandards';
import type { PreviewParts } from '@/screens/resources/FilePreview';
import { sdkTyping } from '@/screens/channels/sdkTransport';
import type { SendTyping } from '@/screens/channels/typing';
import {
    FundsOnNoClick,
    LinkedFileCard,
    ModelConnectLink,
    NO_CARDS,
    useNoToolServerSignIn,
    useV1ToolApps,
    workAddress,
    workspacePreviewParts,
    AppConnectLink,
    reconnectByLink,
} from './slotStandards';

// ── an agent's turns ───────────────────────────────────────────────────────

export interface TurnCardParts {
    /** Around a thread: what its turns' cards read, the work they started followed as `follow` follows it. */
    Provider: ComponentType<{ thread: Thread; follow: ThreadJobs; children: ReactNode }>;
    /** Under a turn's words: a card for each call that has one; `asked`, what the person asked in the message it
     *  answers. Nothing where none has one. */
    Cards: ComponentType<{ turn: TurnEntry; asked: string | null }>;
}

/** Under an agent's turns: a card for what a call did (a purchase held for a yes, an account to connect, a build on its
 *  canvas, a long action followed until it settles). Nothing stands there: each call stays a row of the turn's steps. */
export const TURN_CARDS = slot<TurnCardParts>('work.turn.cards', NO_CARDS);

export interface MarkdownProps {
    content: string;
    className?: string;
    /** A single line break is a break, as in a chat message. */
    breaks?: boolean;
}

/** A reply's, a question's or a browser's found text, drawn from its Markdown. The standard draws it as a code
 *  repository's README is. */
export const REPLY_MARKDOWN = slot<ComponentType<MarkdownProps>>('work.reply.markdown', StandardMarkdown);

/** A file a texted or emailed message carried, as a card in the message. The standard is a link that opens it. */
export const MESSAGE_FILE = slot<ComponentType<{ name: string; url: string }>>('work.message.file', LinkedFileCard);

/** A model's name as people read it, by its id (`anthropic/claude-sonnet-5-5`); undefined where the host knows none. */
export const MODEL_NAME = slot<(model: string) => string | undefined>('work.model.name', () => undefined);

// ── connecting ──────────────────────────────────────────────────────────────

/** An app an agent can use as tools. */
export interface ToolApp {
    /** Its node type (`automation-gmail`), which names and marks it. */
    value: string;
    label: string;
    /** The credential types one of its accounts may be. */
    acceptedCredentialTypes: string[];
    /** Its glyph and colour where the host draws one; else its node's mark is drawn. */
    Icon?: BrandIconComponent;
    iconColor?: string;
}

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

export interface AppConnecting {
    /** The dialog that connects one of an app's accounts, handing back the account that lands (`credential:<id>`'s
     *  id) and closing itself as `onClose` says. */
    Connect: ComponentType<{ app: ToolApp; name: string; onConnected: (credentialId: string) => void; onClose: () => void }>;
    /** Connects again an account connected in the app (its origin `app`, its ref `credential:<id>`) that stopped
     *  working; `title` names it in what's said if it can't. */
    reconnect: (account: { credentialType?: string; credentialId: string }, client: NoClick, title: string) => void;
    /** Calls `changed` whenever an account was connected or connected again here, until the returned function runs. */
    subscribe?: (changed: () => void) => () => void;
}

/** Connecting an app's account where it's needed (an agent's tools, a trigger's account). The standard makes the
 *  connection and opens its connect page on NoClick in a new tab, then waits for the account to land. */
export const CONNECT_APP = slot<AppConnecting>('work.connect.app', { Connect: AppConnectLink, reconnect: (account, client, title) => void reconnectByLink(client, `credential:${account.credentialId}`, title) });

/** Another way to run a model, offered in the connect dialog beside the one it opens on. */
export interface OtherWay {
    key: string;
    label: string;
    credentialType: string;
    onPick: () => void;
}

export interface ModelConnectProps {
    /** Open on this way of running it: an AI account's credential type (`agent_claude_code_oauth`); closed when null. */
    credentialType: string | null;
    /** The model provider that way is an account with (`anthropic`). */
    integration: string | null;
    title?: string;
    /** Why it's asked (the account it replaces was signed out). */
    description?: string;
    others: OtherWay[];
    onOpenChange: (open: boolean) => void;
    /** The account that landed: its credential's id. */
    onConnected: (credentialId: string) => void;
}

/** Connecting the AI account a model needs, from the model picker. The standard makes the connection and opens its
 *  connect page on NoClick (a key, or signing in with a plan) in a new tab, then waits for it to land. */
export const CONNECT_MODEL = slot<ComponentType<ModelConnectProps>>('work.connect.model', ModelConnectLink);

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
