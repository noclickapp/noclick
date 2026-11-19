// Slots several screens draw (src/slots.ts): each with what stands there when no host fills it. A slot only one screen
// draws is declared beside that screen instead (`screens/<screen>/slots.ts`).
import type { ComponentType } from 'react';
import { slot } from '@/slots';
import type { BrandIconComponent } from './BrandIcon';
import type { MarkSize } from './primitives';
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
    /** The integration it's a connection to (`google_sheets`). */
    integration: string;
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
