// The console's slots: the places in it a host may fill (src/slots.ts), each with what stands there otherwise. A
// connection's mark, which other screens draw too, is the shared `connection.mark` (src/ui/slots.ts).
import type { ComponentType } from 'react';
import type { CardProgram } from 'noclick';
import { slot } from '@/slots';
import { IssuerLink } from './slotStandards';

/** Under a button that makes a key, approves a command line's sign-in or copies the setup prompt: what taking that
 *  action accepts. Nothing stands there until a host has terms of its own to name. */
export const TERMS = slot<ComponentType<{ action: string; className?: string }>>('console.terms', () => null);

/** On the cards onboarding page, under "Your company's details", for the account's signed-in owner: the card issuer's
 *  own form. The standard, and what a console acting as a key always shows, links to where the application is
 *  finished. */
export const CARD_ISSUER_FORM = slot<ComponentType<{ program: CardProgram }>>('console.cards.issuerForm', IssuerLink);
