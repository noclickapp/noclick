// The console's slots: the places in it a host may fill (src/slots.ts), each with what stands there otherwise.
import type { ComponentType } from 'react';
import type { CardProgram, Project } from 'noclick';
import { slot } from '@/slots';
import type { MarkSize } from '@/ui/primitives';
import { IssuerLink, StandardAppsTrash, StandardCredentialMark, standardCredentialLabel } from './slotStandards';

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

export interface TrashEntry {
    id: string;
    name: string;
    trashedAt: string | null;
    purgeAfter: string | null;
}

export interface AppsTrashProps {
    /** Never empty: the place isn't drawn while the trash holds no app. */
    entries: TrashEntry[];
    /** The clock the page draws times against, as an ISO time. */
    now: string;
    /** Each throws an Error saying why it couldn't. */
    onRestore: (entry: TrashEntry) => Promise<void>;
    onPurge: (entry: TrashEntry) => Promise<void>;
}

/** Under the Apps list: the apps that were deleted, each to restore or purge. The standard is a plain list. */
export const APPS_TRASH = slot<ComponentType<AppsTrashProps>>('console.apps.trash', StandardAppsTrash);

/** In an app's drawer, after its bindings: its Durable Object classes. Nothing stands there otherwise. */
export const APP_DURABLE_OBJECTS = slot<ComponentType<{ project: Project }>>('console.app.durableObjects', () => null);
