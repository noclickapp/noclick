// Buying a domain: read what someone typed as a name (and maybe its ending),
// ask a registrar what's free and what it costs, then buy one in the buyer's
// name, with the price shown first. The registrar is a seam: the hosted
// service answers through its platform API, and tests pass their own.
import { useRef, useState } from 'react';
import type { RegistrantContact } from '~/lib/domainRegistrant';

export interface DomainOffer {
    domain: string;
    /** Without the dot: "com". */
    ending: string;
    /** What buying it charges now, for `years`, in US dollars. */
    priceUsd: number;
    /** The term the price registers it for: the ending's shortest (two years for .ai). */
    years: number;
    /** What each renewal of `years` costs afterwards (null when the registry hasn't said). */
    renewalUsd: number | null;
    /** A name close to the one asked for (getacme.com), rather than that name on another ending. */
    close?: boolean;
    /** The registry prices this name above its usual rate. */
    premium?: boolean;
    /** A trademark claims notice the registrant must see before buying the name. */
    claimsNotice?: string | null;
}

export interface DomainSearch {
    /** The domain asked for (the name on its first ending when none was typed), and whether it can be bought. */
    asked: { domain: string; status: 'available' | 'taken' | 'unavailable' };
    /** What can be bought: the asked domain first when it's free, then its other endings, then close names. */
    offers: DomainOffer[];
}

/** What a purchase asks of the buyer, read once before the first checkout. */
export interface DomainCheckout {
    /** The domain registration agreement the registrant accepts. */
    agreementUrl: string;
    /** The registrant the account's own domains use when a purchase names none (null: each purchase takes details). */
    onFile: { name: string; email: string; organization?: string } | null;
}

export interface DomainPurchaseDetails {
    /** Who it's registered to, with when they accepted the agreement; absent to use the registrant on file. */
    registrant?: RegistrantContact;
    /** The registrant saw the offer's claims notice and still wants the name. */
    acceptClaims: boolean;
}

export interface DomainRegistrar {
    /** The endings it searches, most wanted first. */
    endings: string[];
    search(query: DomainQuery): Promise<DomainSearch>;
    checkout(): Promise<DomainCheckout>;
    /** Places the purchase at the offer's price, never above it. */
    buy(offer: DomainOffer, details: DomainPurchaseDetails): Promise<void>;
}

export type DomainRefusal = 'unavailable' | 'credits';

export interface DomainPurchaseError {
    text: string;
    /** `unavailable`: this instance doesn't sell them; `credits`: the balance can't pay, or is short of a purchase's floor. */
    kind?: DomainRefusal;
}

/** A registrar's refusal, naming what would lift it when something would. */
export class DomainRegistrarError extends Error {
    readonly kind?: DomainRefusal;

    constructor(message: string, kind?: DomainRefusal) {
        super(message);
        this.name = 'DomainRegistrarError';
        this.kind = kind;
    }
}

export interface DomainQuery {
    /** The name without its ending: "acme". */
    name: string;
    ending: string | null;
}

const LABEL = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;

/** What was typed, as a name and maybe an ending: "Acme Labs" → acmelabs, "https://www.acme.ai/x" → acme + ai. Null when it can't be a domain. */
export function parseDomainQuery(text: string): DomainQuery | null {
    const host = text
        .trim()
        .toLowerCase()
        .replace(/^[a-z]+:\/\//, '')
        .replace(/^www\./, '')
        .split(/[/?#]/)[0]
        .replace(/\s+/g, '');
    const labels = host.split('.').filter(Boolean);
    if (!labels.length) return null;
    // A subdomain searches its parent: help.acme.com asks about acme.com.
    const [name, ending] = labels.length > 1 ? labels.slice(-2) : [labels[0], null];
    if (!LABEL.test(name) || (ending !== null && !/^[a-z]{2,24}$/.test(ending))) return null;
    return { name, ending };
}

function failure(e: unknown, fallback: string): DomainPurchaseError {
    if (e instanceof DomainRegistrarError) return { text: e.message, kind: e.kind };
    return { text: e instanceof Error && e.message ? e.message : fallback };
}

export function useDomainPurchase({ registrar, onBought }: { registrar: DomainRegistrar; onBought: (offer: DomainOffer) => void }) {
    const [searched, setSearched] = useState<DomainQuery | null>(null);
    const [result, setResult] = useState<DomainSearch | null>(null);
    const [searching, setSearching] = useState(false);
    const [picked, setPicked] = useState<DomainOffer | null>(null);
    const [checkout, setCheckout] = useState<DomainCheckout | null>(null);
    const [buying, setBuying] = useState(false);
    const [error, setError] = useState<DomainPurchaseError | null>(null);
    // Only the latest search may land: an earlier, slower answer never replaces a newer one.
    const latest = useRef(0);

    const search = async (text: string) => {
        const query = parseDomainQuery(text);
        if (!query) {
            setError(text.trim() ? { text: 'A domain is letters, numbers and hyphens, like acme or acme-labs.' } : null);
            return;
        }
        const seq = ++latest.current;
        setSearching(true);
        setError(null);
        try {
            const found = await registrar.search(query);
            if (seq !== latest.current) return;
            setSearched(query);
            setResult(found);
        } catch (e) {
            if (seq === latest.current) setError(failure(e, 'Could not search for domains.'));
        } finally {
            if (seq === latest.current) setSearching(false);
        }
    };

    /** Opens the checkout for an offer (null goes back to the results); what it asks of the buyer is read once. */
    const pick = async (offer: DomainOffer | null) => {
        setPicked(offer);
        setError(null);
        if (!offer || checkout) return;
        try {
            setCheckout(await registrar.checkout());
        } catch (e) {
            setError(failure(e, 'Could not open the checkout.'));
        }
    };

    const buy = async (details: DomainPurchaseDetails) => {
        if (!picked || buying) return;
        setBuying(true);
        setError(null);
        try {
            await registrar.buy(picked, details);
            onBought(picked);
        } catch (e) {
            setError(failure(e, `Could not buy ${picked.domain}.`));
        } finally {
            setBuying(false);
        }
    };

    return { searched, result, searching, picked, checkout, buying, busy: searching || buying, error, search, pick, buy };
}
