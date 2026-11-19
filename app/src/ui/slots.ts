// Slots several screens draw (src/slots.ts): each with what stands there when no host fills it. A slot only one screen
// draws is declared beside that screen instead (`screens/<screen>/slots.ts`).
import type { ComponentType } from 'react';
import { slot } from '@/slots';
import type { BrandIconComponent } from './BrandIcon';
import type { MarkSize } from './primitives';
import { plainGlyph, StandardCredentialMark, standardCredentialLabel } from './connectionMarkStandards';

/** A service's glyph and its colour, as `BrandIcon` draws it (a Tailwind `text-*` class, a CSS colour, or '' for a mark
 *  that paints its own). */
export interface Glyph {
    Icon: BrandIconComponent;
    iconColor: string;
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
}

/** Beside a connection's, an integration's or an account's name: the service's mark, its glyph, and what it is called.
 *  The standard draws the mark the icon registry holds for it (a plain cube when it holds none), a plain plug for a
 *  glyph, and reads its name off its type. */
export const CONNECTION_MARK = slot<ConnectionMarks>('connection.mark', {
    Mark: StandardCredentialMark,
    label: standardCredentialLabel,
    glyph: plainGlyph,
    accountGlyph: () => plainGlyph(),
    aiGlyph: () => undefined,
    aiCompany: () => undefined,
});
