// What a costly model on NoClick's key needs: a model whose output costs more than $2 a million tokens there (its
// harness list's `noclickKey.needsFundsUsd`) takes that much of funds the account added before an agent goes on it
// (agents/service.py require_model_funds). The account's funds are GET /v1/account's (`balance.funds_usd`, read
// again on focus); the pickers say what a pick lacks and open Add funds in its place, and a move the platform refuses
// for funds opens it too. The platform still judges; these only explain. Add funds opened for a costly model says why
// it needs funds you add, and the change it was opened for is made by itself once they land (useFundsThenSwitch).
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { PaymentRequired } from 'noclick';
import { getAccount } from '@/sdk/owner';
import { invalidateV1 } from '@/sdk/useV1';
import { formatFunds } from '@/lib/formatters';
import { standing, useSlot } from '@/slots';
import { ADD_FUNDS, MODEL_NAME, type CostlyModel } from '../slots';
import { useWorkV1 } from '../agents/reads';
import type { ModelAccount } from './accounts';

const FUNDS_KEY = 'work:account:funds';

/** The funds the account added, in dollars: null where nothing limits it (no plan system), undefined until read or
 *  where it can't be (a person who isn't the account's owner), which judges nothing. */
export function useAddedFunds(): number | null | undefined {
    const { data } = useWorkV1(FUNDS_KEY, (client, signal) => getAccount(client, signal));
    if (!data) return undefined;
    return data.balance.unlimited ? null : (data.balance.funds_usd ?? undefined);
}

/** What a pick lacks: the funds a costly model needs (`needsFunds`) when it runs on NoClick's key (`runsOn`) and the
 *  account's `funds` fall short of them; null when nothing's lacking or it can't be told. */
export function fundsShort(needsFunds: number | null | undefined, runsOn: Pick<ModelAccount, 'kind'> | null, funds: number | null | undefined): number | null {
    if (!needsFunds || runsOn?.kind !== 'noclick' || funds == null || funds >= needsFunds) return null;
    return needsFunds;
}

/** The note a pick that lacks funds wears: "Add $5 to use". */
export const fundsNote = (needs: number) => `Add $${needs} to use`;
/** The same, on a model's row, where the name needs the room. */
export const fundsTag = (needs: number) => `Add $${needs}`;

/** Whether the platform refused a move for want of funds the account added. */
export const refusedForFunds = (error: unknown): error is PaymentRequired => error instanceof PaymentRequired;

/** The costly model a refusal for funds names (its reason `costly_model`, with the model, its price and the funds it
 *  needs), as people read it; null for any other refusal. */
export function costlyModelOf(error: PaymentRequired): CostlyModel | null {
    const d = error.details;
    if (d.reason !== 'costly_model' || typeof d.model !== 'string' || error.requiredUsd === undefined) return null;
    return {
        name: standing(MODEL_NAME)(d.model) ?? d.model.split('/').at(-1) ?? d.model,
        outputUsdPerMillion: typeof d.output_usd_per_million === 'number' ? d.output_usd_per_million : null,
        needsUsd: error.requiredUsd,
    };
}

// A change waiting on funds, by who makes it, held in this browser so it outlives the checkout's round trip (which
// reloads the page); an hour at most.
const HELD_KEY = 'noclick:switch-when-funded';
const HELD_FOR_MS = 60 * 60 * 1000;
interface Held<T> {
    model: CostlyModel;
    change: T;
    at: number;
}

function heldAll(): Record<string, Held<unknown>> {
    try {
        const all = JSON.parse(window.localStorage.getItem(HELD_KEY) ?? '{}') as Record<string, Held<unknown>>;
        for (const [owner, held] of Object.entries(all)) if (!(Date.now() - held.at < HELD_FOR_MS)) delete all[owner];
        return all;
    } catch {
        return {};
    }
}

function keepHeld(owner: string, held: Held<unknown> | null) {
    try {
        const all = heldAll();
        if (held) all[owner] = held;
        else delete all[owner];
        window.localStorage.setItem(HELD_KEY, JSON.stringify(all));
    } catch {
        // Storage refused (a private window): the change waits on this page only.
    }
}

const reasonOf = (error: unknown) => (error instanceof Error && error.message ? error.message : 'NoClick couldn’t make the change.');
const usd = formatFunds;

export interface FundsThenSwitch<T> {
    /** Add funds: for a costly `model`, saying why it needs funds you add, with `change` made once they land; plain
     *  with neither. */
    open: (model?: CostlyModel | null, change?: T) => void;
    dialog: ReactNode;
}

/** Add funds, and the change it was opened for made by itself (`make`) once they land: as soon as the funds read at or
 *  above what the model needs, on this page (the dialog closing, a return to the tab) or after the checkout's round
 *  trip, which comes back here (held under `owner`; null holds it on this page only). What a change made says back is
 *  `make`'s to show. Funds read short say so once and keep it waiting; a refusal of the change itself ends it, saying
 *  why. The funds are read again as the dialog closes. */
export function useFundsThenSwitch<T>(owner: string | null, make: (change: T) => Promise<unknown>): FundsThenSwitch<T> {
    const [open, setOpen] = useState(false);
    const [model, setModel] = useState<CostlyModel | null>(null);
    const [switching, setSwitching] = useState(false);
    const [held, setHeld] = useState<Held<T> | null>(null);
    const funds = useAddedFunds();
    const AddFunds = useSlot(ADD_FUNDS);
    const making = useRef(false);
    const told = useRef<Held<T> | null>(null);
    const makes = useRef(make);
    makes.current = make;

    // One held before the page reloaded (the checkout's round trip).
    useEffect(() => {
        if (owner) setHeld((heldAll()[owner] as Held<T> | undefined) ?? null);
    }, [owner]);

    useEffect(() => {
        if (!held || open || funds === undefined || making.current) return;
        const tellShort = () => {
            if (told.current === held) return;
            told.current = held;
            toast(`Switches to ${held.model.name} once your funds land`, { description: `It needs ${usd(held.model.needsUsd)} of funds you add.` });
        };
        if (funds !== null && funds < held.model.needsUsd) return tellShort();
        const done = () => {
            if (owner) keepHeld(owner, null);
            setHeld(null);
        };
        making.current = true;
        makes.current(held.change).then(done, (error: unknown) => {
            if (refusedForFunds(error)) return tellShort();
            done();
            toast(`Couldn’t switch to ${held.model.name}`, { description: reasonOf(error) });
        }).finally(() => {
            making.current = false;
        });
    }, [held, open, funds, owner]);

    const dialog = (
        <AddFunds
            isOpen={open}
            forModel={model}
            switching={switching}
            onOpenChange={(next) => {
                setOpen(next);
                if (!next) invalidateV1(FUNDS_KEY);
            }}
        />
    );
    return {
        open: (costly = null, change) => {
            const next = costly && change !== undefined ? { model: costly, change, at: Date.now() } : null;
            setModel(costly);
            setSwitching(!!next);
            if (next) {
                told.current = null;
                setHeld(next);
                if (owner) keepHeld(owner, next);
            }
            setOpen(true);
        },
        dialog,
    };
}

/** Add funds with nothing to make once they land; for a costly model it still says why. */
export function useAddFunds(): FundsThenSwitch<never> {
    return useFundsThenSwitch<never>(null, () => Promise.resolve());
}
