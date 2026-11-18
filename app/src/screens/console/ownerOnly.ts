// What only the account's signed-in owner can do, in one table.
//
// A console is handed a client that acts either as the account's owner, signed in to NoClick, or as one of the
// account's API keys (a server holding a key, as this app's does). NoClick's API refuses a key a handful of
// operations, 403 `permission_denied`: making and reading keys, approving a command line's sign-in, changing the
// account, and a few more. Each row below names one thing the console does that rests on such operations. Everything
// that offers it reads this table through `useOwnerOnly`: the sidebar and the palette (which leave an owner-only
// section out), a section opened by its address (which says why it isn't here), and each page's own buttons and reads.
// So a console acting as a key never calls an operation that would refuse it (test/consoleAsKey.test.ts holds that).
import { useCallback } from 'react';
import { useConsole } from './hooks/useConsole';

export const OWNER_ONLY = {
    /** The API keys section, a key's cap on Usage, a key's name beside a call in Logs, and Quickstart's "Create key". */
    keys: {
        what: 'API keys',
        why: 'A key can’t list, make, change or revoke keys.',
        operations: ['GET /v1/keys', 'POST /v1/keys', 'PATCH /v1/keys/{key_id}', 'DELETE /v1/keys/{key_id}', 'GET /v1/public_endpoints'],
    },
    /** The apps a person connected over MCP, on the API keys page. */
    connectedApps: {
        what: 'Connected apps',
        why: 'A key can’t list or revoke the apps a person connected.',
        operations: ['GET /v1/connected_apps', 'DELETE /v1/connected_apps/{grant_id}'],
    },
    /** The page `noclick login` opens, where a person approves a command line's sign-in. */
    cliSignIn: {
        what: 'Sign in the CLI',
        why: 'Only a person signed in to NoClick approves a command line’s sign-in.',
        operations: ['GET /v1/cli/logins/{user_code}', 'POST /v1/cli/logins/{user_code}/answer'],
    },
    /** The prompt for a coding agent, which carries a one-time code that becomes a key (Quickstart, New agent). */
    setupCode: {
        what: 'The coding agent’s setup prompt',
        why: 'A key can’t mint the one-time code that gives a coding agent a key of its own.',
        operations: ['POST /v1/cli/setup_codes'],
    },
    /** The account's defaults in Settings: the region new resources take, what a paused user is told. */
    accountDefaults: {
        what: 'The account’s defaults',
        why: 'A key reads the account and can’t change it.',
        operations: ['PATCH /v1/account'],
    },
    /** The palette's jump to whatever an id names. */
    objectLookup: {
        what: 'Finding an object by its id',
        why: 'A key can’t ask what an id names across the account.',
        operations: ['GET /v1/objects/{ref}'],
    },
    /** The card issuer's own form, on the cards onboarding page. */
    cardIssuerForm: {
        what: 'The card issuer’s form',
        why: 'Only a person signed in to NoClick opens the company’s application for card issuing.',
        operations: ['POST /v1/cards/program/session'],
    },
    /** Asking NoClick for machines. */
    machineAccess: {
        what: 'Asking for machines',
        why: 'Only a person signed in to NoClick asks for machines and accepts their usage policy.',
        operations: ['POST /v1/machines/vetting'],
    },
} as const;

export type OwnerOnly = keyof typeof OWNER_ONLY;

/** Every operation the API refuses a key that this console can reach, as `METHOD /v1/path/{param}`. */
export const OWNER_ONLY_OPERATIONS: readonly string[] = Object.values(OWNER_ONLY).flatMap((row) => row.operations);

/** Whether an operation is one the API refuses a key: its method and its path as sent (`/v1/keys/9b2a…`). */
export function isOwnerOnly(method: string, path: string): boolean {
    const sent = path.split('?')[0].split('/').filter(Boolean);
    return OWNER_ONLY_OPERATIONS.some((operation) => {
        const [verb, template] = operation.split(' ');
        const wanted = template.split('/').filter(Boolean);
        return verb === method.toUpperCase() && wanted.length === sent.length && wanted.every((part, i) => part.startsWith('{') || part === sent[i]);
    });
}

/** Why `what` isn't here, for a console acting as a key to say in its place. */
export function ownerOnlyWhy(what: OwnerOnly): string {
    return `${OWNER_ONLY[what].why} It’s done signed in to NoClick, as the account’s owner.`;
}

/** Whether this console may do `what`: true for the signed-in owner, false for a key. */
export function useOwnerOnly(): (what: OwnerOnly) => boolean {
    const { actsAs } = useConsole();
    return useCallback(() => actsAs === 'owner', [actsAs]);
}
