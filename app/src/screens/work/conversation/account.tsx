// The account a conversation runs on, judged before anyone sends: checked with its provider once a session as the
// conversation opens (POST /v1/connections/{ref}/verify, which spends nothing and asks for real at most every five
// minutes), so a key its provider refuses or a sign-in that ended shows Send's Reconnect at once, not after a failed
// turn. A refusal marks the connection, so the accounts are read again; "unknown" changes nothing. A verdict is
// forgotten once its account is connected again (in place or from here), and a check that failed isn't kept, so the
// next open asks again. The same connect popup answers Send and a failed turn's Reconnect.
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Connection, type HarnessName, type NoClick } from 'noclick';
import { useWorkClient } from '../client';
import { connectAsk, downWord, firstUsable, NOCLICK_KEY, runsUnpicked, waysFor, type AccountKind, type ConnectAsk, type ModelAccount } from '../newAgent/accounts';
import type { AccountChipProps } from '../newAgent/AccountChip';
import { rereadAccounts, useConnections, useHarnesses, useModelAccounts, useModelRoutes } from '../newAgent/catalog';
import { useConnectAi, useModelLabel } from '../newAgent/ModelPicker';
import { useWorkFrames } from '@/sdk/live';
import type { Failure } from '@/lib/agentThread/thread';

/** What the provider said of a connection: it works, it refused it, or it couldn't be asked. */
export interface Check {
    verdict: 'ok' | 'refused' | 'unknown';
    reason: string | null;
    message: string | null;
}

// One check per connection a session, whichever conversation opens it first.
const checks = new WeakMap<NoClick, Map<string, Promise<Check>>>();
// Every view holding a verdict hears when it's forgotten.
const forgetting = new EventTarget();

function checkOnce(client: NoClick, ref: string): Promise<Check> {
    const mine = checks.get(client) ?? new Map<string, Promise<Check>>();
    checks.set(client, mine);
    const kept = mine.get(ref);
    if (kept) return kept;
    const connection = Connection.fromId(ref, { client });
    const found: Promise<Check> = connection.verify().then(
        () => {
            const check = (connection.raw.check ?? {}) as Record<string, unknown>;
            const verdict = check.verdict === 'ok' || check.verdict === 'refused' ? check.verdict : 'unknown';
            return { verdict, reason: typeof check.reason === 'string' ? check.reason : null, message: typeof check.message === 'string' ? check.message : null };
        },
        (error: unknown) => {
            // A check that failed told nothing: the next open asks again.
            if (mine.get(ref) === found) mine.delete(ref);
            throw error;
        }
    );
    mine.set(ref, found);
    return found;
}

/** Forgets what the provider said of `ref` (its account was connected again): views drop it now, the next open asks. */
export function forgetCheck(client: NoClick, ref: string): void {
    checks.get(client)?.delete(ref);
    forgetting.dispatchEvent(new CustomEvent<string>('forget', { detail: ref }));
}

/** The verdict on `ref` (a model connection; never NoClick's key), once its check answers. */
export function useConnectionCheck(ref: string | null, onRefused: () => void): Check | null {
    const client = useWorkClient();
    const [check, setCheck] = useState<{ ref: string; check: Check } | null>(null);
    useEffect(() => {
        if (!ref || ref === NOCLICK_KEY) return;
        let live = true;
        checkOnce(client, ref).then(
            (found) => {
                if (!live) return;
                setCheck({ ref, check: found });
                if (found.verdict === 'refused') onRefused();
            },
            (e: unknown) => console.warn('[work] the connection check failed:', e)
        );
        return () => {
            live = false;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps -- onRefused is read when the check answers
    }, [client, ref]);
    useEffect(() => {
        const forget = (e: Event) => setCheck((held) => (held?.ref === (e as CustomEvent<string>).detail ? null : held));
        forgetting.addEventListener('forget', forget);
        return () => forgetting.removeEventListener('forget', forget);
    }, []);
    return check?.ref === ref ? check.check : null;
}

/** The account as the conversation sees it: as the accounts read it, and refused already where its check says so. */
export function judged(account: ModelAccount, check: Check | null): ModelAccount {
    if (check?.verdict !== 'refused' || downWord(account)) return account;
    return { ...account, connected: false, status: 'disconnected', down: { reason: check.reason === 'signed_out' ? 'signed_out' : 'refused', message: check.message ?? '' } };
}

const PLAN_OF: Record<string, AccountKind> = { anthropic: 'claude_plan', openai: 'chatgpt_plan' };
const KEY_OF: Record<string, AccountKind> = { anthropic: 'anthropic_key', openai: 'openai_key', openrouter: 'openrouter_key' };

/** The kind of account a failed turn's connection is: the one held by its ref, else what its reason says it was. */
export function kindOfFailure(failure: Failure, accounts: readonly ModelAccount[]): Pick<ModelAccount, 'kind' | 'integration'> | null {
    const held = accounts.find((a) => a.id === failure.connection);
    if (held) return held;
    if (!failure.integration) return null;
    const kind = failure.reason === 'signed_out' ? PLAN_OF[failure.integration] : (KEY_OF[failure.integration] ?? 'key');
    return kind ? { kind, integration: failure.integration } : null;
}

export interface ConversationAccount {
    /** What Send asks for while the account it runs on can't run it; null while it can. */
    ask: ConnectAsk | null;
    /** Opens the connect popup: on what Send asks for, or on a failed turn's kind of account. */
    reconnect: (failure?: Failure) => void;
    /** The account chip under the box, as New agent's: the one it runs on, and the others that run its model. */
    chip: AccountChipProps | null;
    dialog: ReactNode;
}

/** What a conversation runs: its harness and model, and the model connection it names (none picked: null). */
export interface RunsOn {
    harness: HarnessName | null;
    model: string | null;
    connection: string | null;
}

/** The account a conversation runs on (`connection`), checked as it opens, and how to connect it again; what lands
 *  becomes its account (`onAccount`). */
export function useConversationAccount({ harness, model, connection }: RunsOn, onAccount: (account: string) => void, onRefused: () => void): ConversationAccount {
    const harnesses = useHarnesses();
    const { accounts, labels } = useModelAccounts();
    const on = harnesses.data?.find((h) => h.name === harness);
    const ref = connection;
    const pick = model ?? '';
    const check = useConnectionCheck(ref, () => {
        rereadAccounts();
        onRefused();
    });
    const { routes, free } = useModelRoutes(on, pick);
    const modelLabel = useModelLabel(on, pick);
    const ways = useMemo(() => (on && pick ? waysFor(on, pick, labels, routes) : []), [on, pick, labels, routes]);
    const client = useWorkClient();
    const connections = useConnections();
    // A connection connected again in place (its link, Connections) says so in a frame: its verdict no longer holds.
    useWorkFrames('platform:resource', (frame) => {
        if (frame.kind !== 'connection' || frame.status !== 'connected') return;
        const moved = connections.data?.find((c) => c.id === frame.id);
        if (moved) forgetCheck(client, moved.origin === 'app' ? moved.id : moved.name);
    });
    // What lands from here is connected: neither it nor the account it replaces keeps a verdict.
    const connecting = useConnectAi((landed) => {
        forgetCheck(client, landed);
        if (ref) forgetCheck(client, ref);
        onAccount(landed);
    });
    const held = accounts?.find((a) => a.id === ref);
    const account = held ? judged(held, check) : null;
    const ask = on && pick && account && downWord(account) ? connectAsk([account], on, pick, ways, routes) : null;
    // What it runs on: its own account while that runs the model, else as an unpicked one runs (`runsUnpicked`).
    const runsOn = on && pick ? (account ?? runsUnpicked(on, firstUsable(accounts ?? [], on, routes, ref))) : null;
    return {
        ask,
        chip:
            on && pick && accounts
                ? {
                      harness: on,
                      model: pick,
                      modelLabel,
                      accounts,
                      account: runsOn,
                      routes,
                      free: !runsOn && free ? free.name : null,
                      picked: !!ref,
                      ask: connectAsk(accounts, on, pick, ways, routes),
                      ways,
                      onPick: onAccount,
                      onConnect: (another) => connecting.connect(on, pick, { another }),
                  }
                : null,
        reconnect: (failure) => {
            if (!on || !pick) return;
            connecting.connect(on, pick, { on: failure ? kindOfFailure(failure, accounts ?? []) : (ask?.lapsed ?? null) });
        },
        dialog: connecting.dialog,
    };
}
