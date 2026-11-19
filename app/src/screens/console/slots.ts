// The console's slots: the places in it a host may fill (src/slots.ts), each with what stands there otherwise.
import type { ComponentType } from 'react';
import type { CardProgram } from 'noclick';
import { slot } from '@/slots';
import type { MarkSize } from '@/ui/primitives';
import { IssuerLink, StandardCredentialMark, standardCredentialLabel } from './slotStandards';

/** Under a button that makes a key, approves a command line's sign-in or copies the setup prompt: what taking that
 *  action accepts. Nothing stands there until a host has terms of its own to name. */
export const TERMS = slot<ComponentType<{ action: string; className?: string }>>('console.terms', () => null);

export interface CredentialMarks {
    /** The mark beside a connection's or an integration's name. */
    Mark: ComponentType<{ credentialType: string; nodeType?: string | null; size?: MarkSize; className?: string }>;
    /** What that service is called. */
    label: (credentialType: string, nodeType?: string | null) => string;
}

/** Beside a connection's or an integration's name: the service's mark, and what it is called. The standard draws the
 *  mark the icon registry holds for it (a plain cube when it holds none) and reads its name off its type. */
export const CONNECTION_MARK = slot<CredentialMarks>('console.connection.mark', { Mark: StandardCredentialMark, label: standardCredentialLabel });

/** On the cards onboarding page, under "Your company's details", for the account's signed-in owner: the card issuer's
 *  own form. The standard, and what a console acting as a key always shows, links to where the application is
 *  finished. */
export const CARD_ISSUER_FORM = slot<ComponentType<{ program: CardProgram }>>('console.cards.issuerForm', IssuerLink);
