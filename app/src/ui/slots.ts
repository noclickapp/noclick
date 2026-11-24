// Slots several screens draw (src/slots.ts): each with what stands there when no host fills it. A slot only one screen
// draws is declared beside that screen instead (`screens/<screen>/slots.ts`).
import type { ComponentType } from 'react';
import type { NoClick } from 'noclick';
import { slot } from '@/slots';
import type { BrandIconComponent } from './BrandIcon';
import type { MarkSize } from './primitives';
import type { ConnectionCheck } from '@/lib/connectionCheck';
import { AppConnectInPlace, AppConnectLink, ModelConnectLink, reconnectByLink } from './connectStandards';
import { plainGlyph, standardAccountNames, StandardCredentialMark, standardCredentialLabel } from './connectionMarkStandards';

/** A service's glyph and its colour, as `BrandIcon` draws it (a Tailwind `text-*` class, a CSS colour, or '' for a mark
 *  that paints its own). */
export interface Glyph {
    Icon: BrandIconComponent;
    iconColor: string;
}

/** What a list of accounts knows of one (a connection as the platform API reads it). */
export interface AccountFacts {
    credentialType: string;
    /** The integration it's a connection to (`google_sheets`); null for what the app keeps that is no app's account
     *  (an agent's environment variables, an MCP server's key). */
    integration: string | null;
    name: string;
    /** The account it reaches, as the platform names it (its login, email, who a check verified it as, its number). */
    account: string | null;
    /** When it was connected, as an ISO time. */
    connectedAt: string | null;
}

/** An account as a list names it. */
export interface AccountNames {
    /** Its app, else its kind of key. */
    app: string;
    /** What tells it apart from another of its app's. */
    line: string;
    /** More names a search finds its app by ("Anthropic" for a Claude account). */
    aliases: string[];
}

export interface ConnectionMarks {
    /** The mark beside a connection's or an integration's name. */
    Mark: ComponentType<{ credentialType: string; nodeType?: string | null; size?: MarkSize; className?: string }>;
    /** What that service is called. */
    label: (credentialType: string, nodeType?: string | null) => string;
    /** The glyph an account of a credential type wears beside its name. */
    glyph: (credentialType: string, metadata?: Record<string, unknown> | null) => Glyph;
    /** An account's glyph as a list of connected accounts draws it: its service's, else its AI company's. */
    accountGlyph: (credential: { credential_type: string; metadata?: Record<string, unknown> | null }) => Glyph;
    /** An AI account's glyph (`agent_…` credential types); undefined where none is known. */
    aiGlyph: (credentialType: string) => Glyph | undefined;
    /** The AI company an `agent_…` account is with, as it's called ("Claude"); undefined where none is known. */
    aiCompany: (credentialType: string) => string | undefined;
    /** How an account reads in a list of accounts: its app and the line that tells it apart. */
    account: (facts: AccountFacts) => AccountNames;
}

/** Beside a connection's, an integration's or an account's name: the service's mark, its glyph, and what it is called.
 *  The standard draws the mark the icon registry holds for it (a plain cube when it holds none), a plain plug for a
 *  glyph, reads its name off its type, and names an account by the account it reaches, else its own name, else when it
 *  was connected. */
export const CONNECTION_MARK = slot<ConnectionMarks>('connection.mark', {
    Mark: StandardCredentialMark,
    label: standardCredentialLabel,
    glyph: plainGlyph,
    accountGlyph: () => plainGlyph(),
    aiGlyph: () => undefined,
    aiCompany: () => undefined,
    account: standardAccountNames,
});

/** An MCP client's marks where its host draws it its own way: the rail's `Icon` (quieted beside the others) and its
 *  `BrandIcon` in its own colours, by the client's key in `MCP_CLIENTS` (`claude-code`). The standard draws each client
 *  by its own mark, and a coding harness by the protocol's. */
export const MCP_CLIENT_MARKS = slot<Readonly<Record<string, { Icon: ComponentType<{ size?: number }>; BrandIcon: ComponentType<{ size?: number }> }>>>('mcp.client.marks', {});

// ── connecting an account ───────────────────────────────────────────────────

/** An app whose account can be connected. */
export interface ConnectableApp {
    /** Its node type (`automation-gmail`), which names and marks it. */
    value: string;
    label: string;
    /** The credential types one of its accounts may be. */
    acceptedCredentialTypes: string[];
    /** Its glyph and colour where the host draws one; else its node's mark is drawn. */
    Icon?: BrandIconComponent;
    iconColor?: string;
}

/** A connection that just landed through a connect dialog (`connect.app`'s `Connect`, `connect.model`), by both of
 *  the names it goes by. */
export interface LandedConnection {
    /** The ref an agent names it by, in its tools or as its model connection: `credential:<id>` for an account connected
     *  in the app, else its named connection's name (`refFor`; `credential:` never names a named connection). */
    ref: string;
    /** The id of the account it holds, which a workflow step keeps in its `credentialIds`. */
    credentialId: string;
}

/** An account that just landed, as a list of accounts names it (its credential's id, name and type). */
export interface LandedAccount {
    id: string;
    name: string;
    credential_type: string;
}

/** What connecting one of a step's accounts in place is handed, under the step's account pickers. */
export interface InPlaceConnectProps {
    /** The step type whose ways in these are (`automation-notion`). */
    nodeType: string;
    /** Its app, as people name it ("Notion"). */
    app: string;
    /** Its name among the integrations the API lists (`notion`), where an account of it connects there; null where
     *  none does (an agent's model account). */
    integration: string | null;
    /** The way in to open on: a credential type the step takes; when absent, the step's first (where a connect page
     *  takes the way in, the app's own first). */
    credentialType?: string;
    /** An account the step points at whose connection dropped: connected again in place, never a new one beside it. */
    repairs?: string;
    /** Start unasked where starting shows something to act on at once (a QR code to scan); a repair waits for a click. */
    autoStart: boolean;
    /** Offer asking someone else to connect it (off where the screen already belongs to someone asking). */
    ask: boolean;
    /** The account that landed, with what connecting it proved (null: nothing could be judged). */
    onConnected: (account: LandedAccount, check: ConnectionCheck | null) => void;
}

/** What entering an account's values again in place is handed, in place of its picker. */
export interface RekeyProps {
    credentialId: string;
    credentialType: string;
    /** Its name, kept unless changed. */
    name: string;
    /** Its way in, as people name it ("Notion OAuth"). */
    label: string;
    /** The schema of its credential class: the values it asks for. */
    schema?: Record<string, unknown>;
    /** Its app, as people name it. */
    app: string;
    /** It's saved, with what saving it proved (null: nothing could be judged); done once the list holds it. */
    onSaved: (check: ConnectionCheck | null) => void | Promise<void>;
    onCancel: () => void;
}

export interface AppConnecting {
    /** The dialog that connects one of an app's accounts for `name` (an agent, say), with the platform client the screen
     *  drawing it reads with, handing back the connection that lands (`LandedConnection`: Work's tools panel names it
     *  by its ref) and closing itself as `onClose` says. */
    Connect: ComponentType<{ app: ConnectableApp; name: string; client: NoClick; onConnected: (landed: LandedConnection) => void; onClose: () => void }>;
    /** Connecting one of a step's accounts in its form, drawn in place under its pickers, with the platform client a
     *  `ClientProvider` above gives where it reads one. */
    InPlace: ComponentType<InPlaceConnectProps>;
    /** Entering an account's values again in a step's form, in place of its picker, where the host keeps those values;
     *  null where it doesn't, and the account is connected again (`reconnect`) instead. */
    Rekey: ComponentType<RekeyProps> | null;
    /** Connects again an account connected in the app (its origin `app`, its ref `credential:<id>`) that stopped
     *  working; `title` names it in what's said if it can't. */
    reconnect: (account: { credentialType?: string; credentialId: string }, client: NoClick, title: string) => void;
    /** Calls `changed` whenever an account was connected or connected again here, until the returned function runs. */
    subscribe?: (changed: () => void) => () => void;
}

/** Connecting an app's account where it's needed (an agent's tools, a trigger's account, a step's form). The standard
 *  makes the connection and opens its connect page on NoClick in a new tab, then waits for the account to land; a
 *  step's form does the same in place, and enters no values itself: an account is connected again at its connect page. */
export const CONNECT_APP = slot<AppConnecting>('connect.app', {
    Connect: AppConnectLink,
    InPlace: AppConnectInPlace,
    Rekey: null,
    reconnect: (account, client, title) => void reconnectByLink(client, `credential:${account.credentialId}`, title),
});

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
    /** The platform client the screen drawing it reads with. */
    client: NoClick;
    onOpenChange: (open: boolean) => void;
    /** The connection that landed: the model picker names it by its ref, an agent step keeps the account it holds. */
    onConnected: (landed: LandedConnection) => void;
}

/** Connecting the AI account a model needs (the model picker's, an agent step's). The standard makes the connection and opens its
 *  connect page on NoClick (a key, or signing in with a plan) in a new tab, then waits for it to land. */
export const CONNECT_MODEL = slot<ComponentType<ModelConnectProps>>('connect.model', ModelConnectLink);
