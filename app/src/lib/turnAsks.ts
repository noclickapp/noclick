// What an agent's turn left waiting on a person, as its message in a channel carries it (the platform's `asks`
// event): accounts to connect over their links, calls held for the owner's OK, links that pay and secrets whose values
// the account types in, each with how it settled once it has (`state`: the operation's own status, or a secret's
// `succeeded` once it holds its keys), an account that landed with which it is and who said they connected it. Who
// asked is the person whose post the turn answered.

/** Someone as the channel names them (an author's shape). */
export interface AskBy {
    type: string;
    id: string | null;
    name: string;
}

export type TurnAsk =
    | { kind: 'connect'; id: string; credentialType: string; label: string; url: string; reason: string | null; state: string | null; account: string | null; by: AskBy | null }
    | { kind: 'approval'; id: string; approvalId: string; summary: string; price: { amount_usd: number; [key: string]: unknown } | null; state: string | null }
    | { kind: 'payment'; id: string; label: string; priceUsd: number | null; billingPeriod: string | null; url: string; state: string | null }
    | { kind: 'secret'; id: string; name: string; keys: string[]; reason: string | null; state: string | null };

export interface TurnAsks {
    turn: string;
    askedBy: AskBy | null;
    asks: TurnAsk[];
}

type Raw = Record<string, unknown>;
const text = (v: unknown) => (typeof v === 'string' ? v : null);
const object = (v: unknown) => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Raw) : null);

function askOf(raw: Raw, named: (by: Raw) => AskBy): TurnAsk | null {
    const id = text(raw.id);
    const state = text(raw.state);
    if (!id) return null;
    if (raw.kind === 'connect' && text(raw.url) && text(raw.credential_type)) {
        const by = object(raw.by);
        return { kind: 'connect', id, credentialType: text(raw.credential_type)!, label: text(raw.label) ?? 'An account', url: text(raw.url)!, reason: text(raw.reason), state, account: text(raw.account), by: by ? named(by) : null };
    }
    if (raw.kind === 'approval' && text(raw.approval_id)) {
        const price = object(raw.price);
        return { kind: 'approval', id, approvalId: text(raw.approval_id)!, summary: text(raw.summary) ?? 'What NoClick asked to do', price: price && typeof price.amount_usd === 'number' ? (price as { amount_usd: number }) : null, state };
    }
    if (raw.kind === 'payment' && text(raw.url)) {
        return { kind: 'payment', id, label: text(raw.label) ?? 'A payment', priceUsd: typeof raw.price_usd === 'number' ? raw.price_usd : null, billingPeriod: text(raw.billing_period), url: text(raw.url)!, state };
    }
    const keys = Array.isArray(raw.keys) ? raw.keys.flatMap((k) => text(k) ?? []) : [];
    if (raw.kind === 'secret' && text(raw.name) && keys.length) {
        return { kind: 'secret', id, name: text(raw.name)!, keys, reason: text(raw.reason), state };
    }
    return null;
}

/** As the platform names someone. */
const asSaid = (by: Raw): AskBy => ({ type: text(by.type) ?? '', id: text(by.id), name: text(by.name) ?? '' });

/** Asks as a turn's result keeps them (`asks`: its reply in the chat's history, its turn's end on the watch), its
 *  people named by `named`. */
export function askList(raw: unknown, named: (by: Raw) => AskBy = asSaid): TurnAsk[] {
    return (Array.isArray(raw) ? raw : []).flatMap((a) => (object(a) ? (askOf(object(a)!, named) ?? []) : []));
}

/** A channel message's asks from its `asks` event, its people named by `named` (as the channel reads authors); null
 *  for any other event. */
export function turnAsksOf(event: unknown, named: (by: Raw) => AskBy): TurnAsks | null {
    const raw = object(event);
    if (raw?.type !== 'asks') return null;
    const asks = askList(raw.asks, named);
    const askedBy = object(raw.asked_by);
    return asks.length ? { turn: text(raw.turn) ?? '', askedBy: askedBy ? named(askedBy) : null, asks } : null;
}
