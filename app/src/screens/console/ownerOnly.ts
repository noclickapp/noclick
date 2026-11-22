// What only the account's signed-in owner can do, in one table.
//
// A screen is handed a client that acts either as the account's owner, signed in to NoClick, or as one of the
// account's API keys (a server holding a key, as this app's does). NoClick's API refuses a key a handful of
// operations, 403 `permission_denied`: making and reading keys, approving a command line's sign-in, changing the
// account, and a few more; and a few others need a scope the account's `*` key doesn't hold (an agent's sandbox, a
// card's number). Each row below names one thing a screen does that rests on such operations, or (`appOnly`) one the
// API doesn't offer at all, done only signed in to NoClick's own app. Everything that offers
// it reads this table through `useOwnerOnly`: the sidebar and the palette (which leave an owner-only section out), a
// section opened by its address (which says why it isn't here, and links to where its owner does it), and each page's
// own buttons and reads. So a screen acting as a key never calls an operation that would refuse it (consoleAsKey and
// resourcesAsKey hold that; NoClick's own tests call every operation the screens make as a key, and hold the table to
// what refuses one).
import { useCallback, useContext } from 'react';
import { ConsoleContext } from './hooks/useConsole';

export interface OwnerOnlyRow {
    what: string;
    /** Why a key can't, in one sentence. */
    why: string;
    /** The operations it rests on, as `METHOD /v1/path/{param}`; none for what the API doesn't offer (`appOnly`). */
    operations: readonly string[];
    /** What the API doesn't offer at all, so it rests on no operation: only a person signed in to NoClick's own app does
     *  it, and a screen acting as a key says so where it would offer it. */
    appOnly?: true;
    /** Where its owner does it: the page of NoClick's own console, and what the link to it says. Absent where no page
     *  there is the place for it. */
    at?: { page: string; link: string };
    /** Where a key is refused the operations for only some of what they name, which: the screen asks each thing
     *  whether it's one, and the operations are left out of `OWNER_ONLY_OPERATIONS`. Absent: refused whatever they
     *  name. */
    only?: string;
    /** The scope a key needs for it, where a key given that scope may (the account's own key with every scope, `*`,
     *  hasn't it): a screen offers it to a key as to the owner, and shows the API's refusal as it comes. The operations
     *  stay among what the API refuses the account's `*` key (`refusedToAccountKey`), and out of `OWNER_ONLY_OPERATIONS`. */
    scope?: string;
}

export const OWNER_ONLY = {
    /** The API keys section, a key's cap on Usage, a key's name beside a call in Logs, and Quickstart's "Create key". */
    keys: {
        what: 'API keys',
        why: 'A key can’t list, change or revoke keys, and makes one only while it holds keys:create, which a key with every scope doesn’t.',
        operations: ['GET /v1/keys', 'POST /v1/keys', 'PATCH /v1/keys/{key_id}', 'DELETE /v1/keys/{key_id}', 'GET /v1/public_endpoints'],
        at: { page: 'keys', link: 'Manage API keys on NoClick' },
    },
    /** The apps a person connected over MCP, on the API keys page. */
    connectedApps: {
        what: 'Connected apps',
        why: 'A key can’t list, revoke or restore the apps a person connected.',
        operations: ['GET /v1/connected_apps', 'DELETE /v1/connected_apps/{grant_id}', 'POST /v1/connected_apps/{grant_id}/restore'],
        at: { page: 'keys', link: 'See connected apps on NoClick' },
    },
    /** The page `noclick login` opens, where a person approves a command line's sign-in. */
    cliSignIn: {
        what: 'Sign in the CLI',
        why: 'Only a person signed in to NoClick approves a command line’s sign-in.',
        operations: ['GET /v1/cli/logins/{user_code}', 'POST /v1/cli/logins/{user_code}/answer'],
        at: { page: 'cli', link: 'Approve it on NoClick' },
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
    /** Raising or removing the account's monthly spending cap, in Settings → Plan and billing (lowering it, or setting
     *  one where there's none, a key may: the same operation). */
    accountCap: {
        what: 'Raising or removing the spending cap',
        why: 'A key lowers the account’s monthly spending cap, or sets one where there’s none; raising or removing it is the owner’s.',
        operations: ['PUT /v1/usage/limits/account'],
        only: 'a cap above the one in place, or none where one is set; a key lowers it or sets one where there’s none',
    },
    /** The numbers linked to the account, in Settings → Phone: a linked number signs in to the account. */
    accountPhones: {
        what: 'Linking phone numbers',
        why: 'A number linked to the account signs in to it, so a key links one only with the account:phones scope, which an account’s key with every scope (*) doesn’t hold and this app’s key doesn’t carry.',
        operations: ['GET /v1/account/phones', 'POST /v1/account/phones', 'POST /v1/account/phones/verify', 'DELETE /v1/account/phones/{phone}'],
    },
    /** A team workspace's spending cap, which the account paying for the workspace sets, in Settings → Plan and
     *  billing. */
    teamCap: {
        what: 'A team workspace’s spending cap',
        appOnly: true,
        why: 'The API reads and sets the account’s own cap, so a key can’t read or set the cap of a team workspace that another account may pay for.',
        operations: [],
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
        why: 'Only a person signed in to NoClick asks for machines and accepts their usage policy, or the account’s server with a key given the machines:vetting scope, which this app’s key doesn’t carry.',
        operations: ['POST /v1/machines/vetting'],
        at: { page: 'resources/machines', link: 'Ask on NoClick' },
    },
    /** A card's number, revealed on its page. */
    cardReveal: {
        what: 'Revealing a card’s number',
        why: 'A key reveals a card’s number only with the cards:reveal scope, which an account’s key with every scope (*) doesn’t hold.',
        operations: ['POST /v1/cards/{card_id}/reveal'],
    },
    /** Entering a space the owner joined in another account, and leaving it. */
    joinedSpaces: {
        what: 'Spaces you joined in other accounts',
        why: 'A key is the account, not the person who joined someone else’s space.',
        operations: ['POST /v1/me/workspaces/{workspace_id}/sessions', 'DELETE /v1/me/workspaces/{workspace_id}'],
    },
    /** Opening the personal space to people, so they can be invited into it. */
    sharePersonalSpace: {
        what: 'Sharing your personal space',
        why: 'Only the account’s owner, signed in, opens their personal space to people.',
        operations: ['POST /v1/me/personal_space'],
    },
    /** An agent's sandbox: its files, a command run there, and a shell of your own on it. */
    agentSandbox: {
        what: 'An agent’s sandbox',
        scope: 'agents:terminal',
        why: 'A key reaches an agent’s sandbox only with the agents:terminal scope, which an account’s key with every scope (*) doesn’t hold.',
        operations: [
            'GET /v1/agents/{agent_id}/conversations/{conversation}/sandbox/files',
            'POST /v1/agents/{agent_id}/conversations/{conversation}/sandbox/exec',
            'POST /v1/agents/{agent_id}/conversations/{conversation}/sandbox/shell',
        ],
    },
    /** Approving or declining a purchase or a deletion NoClick holds for the owner's yes: on its card in the chat, and in
     *  the chat's Beside. */
    approvals: {
        what: 'Approving a held purchase or deletion',
        why: 'Only the account’s owner approves a purchase or a deletion NoClick holds for their yes, signed in or from the link NoClick sends them.',
        operations: ['POST /v1/approvals/{approval_id}/answer'],
    },
    /** Approving or declining a call NoClick holds for the owner's yes. */
    heldCalls: {
        what: 'Approving a held call',
        scope: 'approvals:answer',
        why: 'A key answers a call NoClick holds for the owner’s yes only with the approvals:answer scope, which an account’s key with every scope (*) doesn’t hold, and never one made with it.',
        operations: ['POST /v1/humans/requests/{request_id}/answer'],
        only: 'a held call (its request reads `owner_only`); a key answers the account’s other requests',
    },
    /** Choosing who else may use an account connected in the app, and leaving one shared with you, on its page in
     *  Connections. */
    connectionSharing: {
        what: 'Sharing a connected account',
        appOnly: true,
        why: 'The API doesn’t share connected accounts, so a key can’t choose who else uses one.',
        operations: [],
    },
    /** Letting a connected account's action run without the owner's OK again, on its Approvals page (adding one is
     *  `POST /v1/connections/{ref}/require_approval`, which a key may make). */
    connectionApprovals: {
        what: 'Lifting a connected account’s approvals',
        why: 'Lifting one takes the owner, their word through an agent, or a key they gave the approvals:policy scope, which this app’s key doesn’t carry.',
        operations: ['DELETE /v1/connections/{ref}/require_approval'],
    },
} as const satisfies Record<string, OwnerOnlyRow>;

export type OwnerOnly = keyof typeof OWNER_ONLY;

/** Every operation the API refuses a key whatever it names that a screen can reach, as `METHOD /v1/path/{param}`. A
 *  row refused for only some of what it names (`only`) isn't here: its screen asks each thing. */
export const OWNER_ONLY_OPERATIONS: readonly string[] = Object.values(OWNER_ONLY as Record<string, OwnerOnlyRow>).flatMap((row) => (row.only || row.scope ? [] : row.operations));

/** What the API refuses the account's own key with every scope (`*`) whatever it names: the owner's alone, and what
 *  needs a scope `*` doesn't hold. A fixture answering as such a key refuses these. */
const REFUSED_TO_ACCOUNT_KEY: readonly string[] = Object.values(OWNER_ONLY as Record<string, OwnerOnlyRow>).flatMap((row) => (row.only ? [] : row.operations));

const matches = (operations: readonly string[], method: string, path: string): boolean => {
    const sent = path.split('?')[0].split('/').filter(Boolean);
    return operations.some((operation) => {
        const [verb, template] = operation.split(' ');
        const wanted = template.split('/').filter(Boolean);
        return verb === method.toUpperCase() && wanted.length === sent.length && wanted.every((part, i) => part.startsWith('{') || part === sent[i]);
    });
};

/** Whether an operation is one the API refuses any key, so no screen acting as one makes it: its method and its path as
 *  sent (`/v1/keys/9b2a…`). */
export function isOwnerOnly(method: string, path: string): boolean {
    return matches(OWNER_ONLY_OPERATIONS, method, path);
}

/** Whether the API refuses the operation to the account's own `*` key (`isOwnerOnly`, and what needs a scope it lacks). */
export function refusedToAccountKey(method: string, path: string): boolean {
    return matches(REFUSED_TO_ACCOUNT_KEY, method, path);
}

/** The scope a key needs for the operation, where a key given it may make it; null for any other. */
export function scopeFor(method: string, path: string): string | null {
    const row = Object.values(OWNER_ONLY as Record<string, OwnerOnlyRow>).find((r) => r.scope && matches(r.operations, method, path));
    return row?.scope ?? null;
}

/** What only the owner can do that is done on `page` of NoClick's own console (`keys`: API keys and connected apps). */
export function ownerOnlyAt(page: string): OwnerOnly[] {
    return (Object.keys(OWNER_ONLY) as OwnerOnly[]).filter((what) => (OWNER_ONLY[what] as OwnerOnlyRow).at?.page === page);
}

/** Why `what` isn't here, for a console acting as a key to say in its place. */
export function ownerOnlyWhy(what: OwnerOnly): string {
    return `${OWNER_ONLY[what].why} It’s done signed in to NoClick, as the account’s owner.`;
}

/** Whether this screen may do `what`: true for the signed-in owner, false for a key. A piece drawn outside a console's
 *  context (a page of a host that signs its owner in, drawing another screen's parts) acts as that owner. */
export function useOwnerOnly(): (what: OwnerOnly) => boolean {
    const actsAs = useContext(ConsoleContext)?.actsAs ?? 'owner';
    // What a key given its scope may do is offered to every key: the API's answer says whether this one may.
    return useCallback((what: OwnerOnly) => actsAs === 'owner' || !!(OWNER_ONLY[what] as OwnerOnlyRow).scope, [actsAs]);
}
