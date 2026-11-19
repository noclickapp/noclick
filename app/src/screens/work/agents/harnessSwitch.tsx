// Moving an existing agent onto another harness, from its conversation's model picker or its profile: the account it
// runs on there is picked as New agent picks one (accounts.ts), with no question where only one of yours runs it, a
// choice where several do, and the app's own connect popup where none does, the move made once it lands. A move onto a
// costly model on NoClick's key opens Add funds and is made once they land. A refusal says what it needs in plain
// words, never the platform's own text.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { Agent, NoClickError, type HarnessInfo, type HarnessName } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import { useWorkClient } from '../client';
import { accountKinds, accountTitle, NOCLICK_KEY, NOCLICK_KEY_ACCOUNT, switchAccount, type ModelAccount } from '../newAgent/accounts';
import { useHarnesses, useModelAccounts } from '../newAgent/catalog';
import { costlyModelOf, refusedForFunds, useFundsThenSwitch } from '../newAgent/funds';
import { useConnectAi } from '../newAgent/ModelPicker';
import { rereadAgent } from '../profile/reads';
import { harnessLabel, harnessName } from './harness';
import { AGENTS_KEY, nameOf, STATES_KEY } from './reads';

/** A move onto `harness`, on `model` (its default when left out). */
export interface HarnessMove {
    harness: HarnessName;
    model?: string;
}

/** What starting a move did: made it, wait on a choice of account or a connect, or nothing yet (the harnesses and the
 *  accounts aren't read). */
export type SwitchStep = 'moving' | 'choose' | 'connect' | 'unread';

export interface HarnessSwitch {
    start: (move: HarnessMove) => SwitchStep;
    /** A move waiting on which of your accounts it runs on; null when none waits. */
    choosing: { move: HarnessMove; harness: HarnessInfo; accounts: ModelAccount[] } | null;
    choose: (account: string) => void;
    cancel: () => void;
    /** The move under way; null when none is. */
    moving: HarnessMove | null;
    dialog: ReactNode;
}

/** Why a move was refused, in plain words: what it needs and what to do. `account` is the one it was to run on. */
export function switchRefusal(error: unknown, name: string, from: HarnessName, to: HarnessInfo, model: string, account: ModelAccount | null, labels?: ReadonlyMap<string, string>): { title: string; description: string } {
    const title = `${name} stays on ${harnessName(from)}`;
    const label = harnessLabel(to.name);
    const field = error instanceof NoClickError ? error.details.field : undefined;
    if (field === 'model_connection') {
        const kinds = accountKinds(to, model, labels);
        if (!account) return { title, description: `${label} needs ${kinds}. Connect one, then switch again.` };
        const on = account.kind === 'noclick' ? 'NoClick’s key' : `Your ${accountTitle(account)}`;
        return { title, description: `${on} can’t run that model on ${label}. Pick another model, or connect ${kinds}.` };
    }
    if (field === 'model') return { title, description: `${label} can’t run that model. Pick another from its list.` };
    return { title, description: `NoClick couldn’t move it to ${label}. Try again in a moment, or ask NoClick in Chat to move it.` };
}

/** Moves `agent` onto another harness: `onMoved` follows each move made (a conversation reads its settings again),
 *  `onRefused` each one refused or waiting on funds. */
export function useHarnessSwitch(agent: Agent | null, { onMoved, onRefused }: { onMoved?: () => void; onRefused?: () => void } = {}): HarnessSwitch {
    const client = useWorkClient();
    const harnesses = useHarnesses();
    const { accounts, labels } = useModelAccounts();
    const [choosing, setChoosing] = useState<HarnessSwitch['choosing']>(null);
    const [moving, setMoving] = useState<HarnessMove | null>(null);
    // The move a connect waits on, made once what lands reads connected.
    const waiting = useRef<HarnessMove | null>(null);
    const told = useRef({ onMoved, onRefused });
    told.current = { onMoved, onRefused };
    const name = agent ? nameOf(agent) : 'It';
    const from = agent?.harness ?? 'sdk';

    const apply = async ({ move, account }: { move: HarnessMove; account: string }) => {
        if (!agent) return;
        // NoClick's own runtime on NoClick's key names no connection.
        const modelConnection = move.harness === 'sdk' && account === NOCLICK_KEY ? null : account;
        await Agent.fromId(agent.id, { client }).update({ harness: move.harness, ...(move.model ? { model: move.model } : {}), modelConnection });
        toast(`${name} runs on ${harnessName(move.harness)} now`, { description: `Same conversation: its next turn picks it up on ${harnessLabel(move.harness)}.` });
        rereadAgent(agent.id);
        invalidateV1(AGENTS_KEY);
        invalidateV1(STATES_KEY);
        told.current.onMoved?.();
    };
    const adding = useFundsThenSwitch<{ move: HarnessMove; account: string }>(agent ? `harness:${agent.id}` : null, apply);
    const run = async (move: HarnessMove, account: string) => {
        setChoosing(null);
        setMoving(move);
        try {
            await apply({ move, account });
        } catch (error) {
            told.current.onRefused?.();
            if (refusedForFunds(error)) return adding.open(costlyModelOf(error), { move, account });
            console.warn('[work] the harness move was refused:', error);
            const to = harnesses.data?.find((h) => h.name === move.harness);
            const on = account === NOCLICK_KEY ? NOCLICK_KEY_ACCOUNT : (accounts?.find((a) => a.id === account) ?? null);
            const words = to && switchRefusal(error, name, from, to, move.model ?? to.defaultModel, on, labels);
            toast(words ? words.title : `${name} stays on ${harnessName(from)}`, { description: words ? words.description : undefined });
        } finally {
            setMoving(null);
        }
    };
    const connecting = useConnectAi((landed) => {
        const move = waiting.current;
        waiting.current = null;
        if (move) void run(move, landed);
    });
    // A choice left open belongs to the agent it was offered for.
    useEffect(() => setChoosing(null), [agent?.id]);

    return {
        start: (move) => {
            const info = harnesses.data?.find((h) => h.name === move.harness);
            if (!agent || !info || !accounts) {
                toast('Still reading your accounts', { description: 'Try again in a moment.' });
                return 'unread';
            }
            const model = move.model ?? info.defaultModel;
            const step = switchAccount(accounts, info, model, agent.modelConnection);
            if ('account' in step) {
                // A move naming no model takes, on NoClick's key, the first model the key runs, as New agent does.
                const onKey = !move.model && step.account.kind === 'noclick' && info.name !== 'sdk' ? info.noclickKey.models[0] : undefined;
                void run(onKey ? { ...move, model: onKey } : move, step.account.id);
                return 'moving';
            }
            if ('choose' in step) {
                setChoosing({ move, harness: info, accounts: step.choose });
                return 'choose';
            }
            waiting.current = move;
            connecting.connect(info, model);
            return 'connect';
        },
        choosing,
        choose: (account) => choosing && void run(choosing.move, account),
        cancel: () => setChoosing(null),
        moving,
        dialog: (
            <>
                {connecting.dialog}
                {adding.dialog}
            </>
        ),
    };
}
