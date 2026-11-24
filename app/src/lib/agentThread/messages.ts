// What an agent conversation's messages say and point at, the same for every page that draws one (Work, the Chat
// page): the line a message ends with naming what it points at (an automation, an account), taken back off for its
// chips; the words a turn that ended says by how it ended; what a refusal for an account out of funds carries for its
// card; and what the stream announced of an approval or a long action, as the answer its card reads.
import type { JsonObject } from 'noclick';

/** What a message points its agent at: an automation, or a connected account. */
export interface ChatReference {
    kind: 'automation' | 'account';
    /** An automation's workflow id; an account's credential id (one connected in the app), or `connection:<id>` for a
     *  named connection. */
    id: string;
    label: string;
    /** The team workspace an account connected in the app was picked in (its id), where it's used: one shared with
     *  that team is the team's to use there alone. */
    organizationId?: string;
}

/** An account reference's id for a named connection (the platform API's connection id). */
export const NAMED_CONNECTION = 'connection:';

/** The status a turn shows while its conversation is compacted before the model goes on. */
export const CATCHING_UP = 'Catching up on the conversation';
/** What a turn that failed for no reason the owner can act on says, word for word as the API's history says it: the
 *  error's own words stay on its operation and in the logs. */
export const TURN_FAILED_LINE = 'Sorry, I hit a problem on my side. Please try that again in a moment.';

/** What a turn that ended says, by its operation's status (the stream's `turn_end` says it): its reply's `text` when
 *  it succeeded; when it failed, the line the stream gave for a person (why a turn lost with its place was lost) or
 *  else the failure line; nothing when it was canceled or expired. */
export function turnEndText(status: string | null, text: string | null | undefined): string {
    return status === 'succeeded' ? (text ?? '') : status === 'failed' ? text || TURN_FAILED_LINE : '';
}

/** What NoClick's refusal for an account that ran out carries for the card under it (its `out_of_funds`: the line it
 *  said, and the invite row's link), on the turn's error or on the reply the conversation kept in its place. */
export function outOfFundsOf(value: unknown): Record<string, unknown> | undefined {
    return value && typeof value === 'object' && typeof (value as { said?: unknown }).said === 'string' ? (value as Record<string, unknown>) : undefined;
}

// /v1 takes no empty message; files sent on their own say so.
const FILES_ONLY = '(Files attached.)';
const ABOUT = /\n*\(About (.+)\.\)$/s;
const NAMED = /the (automation|account) “([^”]*)” \((workflow |credential:|connection )([\w-]+)(?:, organization_id ([\w-]+))?\)/g;

function listed(items: string[]): string {
    return items.length < 2 ? (items[0] ?? '') : `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}

/** How a message names what it points at, by the id the platform API looks each up by (and the team workspace it
 *  takes as `organization_id`, for an account picked in one). */
function pointsAt(r: ChatReference): string {
    if (r.kind === 'automation') return `the automation “${r.label}” (workflow ${r.id})`;
    if (r.id.startsWith(NAMED_CONNECTION)) return `the account “${r.label}” (connection ${r.id.slice(NAMED_CONNECTION.length)})`;
    return `the account “${r.label}” (credential:${r.id}${r.organizationId ? `, organization_id ${r.organizationId}` : ''})`;
}

/** The message the agent gets: the words, with what they point at named so the agent can look it up. */
export function composeMessage(text: string, references: readonly ChatReference[], hasFiles: boolean): string {
    const named = references.map(pointsAt);
    const words = [text.trim(), named.length ? `(About ${listed(named)}.)` : ''].filter(Boolean).join('\n\n');
    return words || (hasFiles ? FILES_ONLY : '');
}

/** A sent message as its bubble shows it: the words and their chips, the line naming them taken back off. */
export function readMessage(text: string): { text: string; references: ChatReference[] } {
    if (text === FILES_ONLY) return { text: '', references: [] };
    const about = ABOUT.exec(text);
    const references = about
        ? [...about[1].matchAll(NAMED)].map((m) => ({
              kind: m[1] as ChatReference['kind'],
              label: m[2],
              id: m[3] === 'connection ' ? `${NAMED_CONNECTION}${m[4]}` : m[4],
              ...(m[5] ? { organizationId: m[5] } : {}),
          }))
        : [];
    return about && references.length ? { text: text.slice(0, about.index), references } : { text, references: [] };
}

/** What the stream announced of a held approval or a long action (`kind` `approval` or `operation`), as the answer of
 *  a call its card draws from. */
export function announcedResult(a: JsonObject): JsonObject {
    return a.kind === 'approval'
        ? { status: 'awaiting_approval', approval_id: a.id, summary: a.summary, price: a.price, expires_at: a.expires_at }
        : { status: a.status, operation_id: a.id, summary: a.summary };
}

