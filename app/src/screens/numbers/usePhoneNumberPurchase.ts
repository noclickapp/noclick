// Buying a phone number: find one in any country numbers are sold in, then buy it. Each number has its own price in
// dollars (a month, and once when bought), which the purchase carries back so the charge is the price shown. A
// purchase link buys through a quote its owner confirms instead (`confirmation`). One hook for every surface that
// sells numbers, each over the transport it hands in: the steps are named (`phone_number:search`, `:buy`, …) and the
// transport answers each however its host reaches NoClick (the SDK, a socket, a form post).
// A number whose country asks for documents is bought with them (uploaded first, through the transport) and answers
// in text, and the carrier reviews them: its order is in review until the carrier approves it (`orders`), and one it
// sends back is corrected and resubmitted.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { heldCallOf, type HeldCall, type HeldState } from '@/sdk/held';

/** The kinds of number, as the carriers name them. */
export type NumberType = 'local' | 'mobile' | 'toll_free' | 'national' | 'shared_cost';
/** What every number must do: take calls, or calls and texts. */
export type NumberFeatures = 'voice' | 'voice_sms';
export type PlaceKind = 'locality' | 'area_code' | 'region';

/** What a number's country asks before it's sold: the holder's address or contact information (`address`,
 *  `contact`), an answer in text (`textual`: one of `values` where it lists them; `example` is the carrier's), a
 *  document, or a step that can't be taken here (`step`). */
export interface NumberRequirement {
    id: string;
    kind: 'address' | 'contact' | 'textual' | 'document' | 'step';
    name: string;
    description: string;
    example: string;
    values: string[];
}

export type NumberNeeds = 'none' | 'address' | 'documents' | 'steps';

/** By requirement id: the text a textual requirement takes, the id of the document a document requirement takes. */
export type RequirementAnswers = Record<string, string>;

/** A document the account filed for a requirement, offered again for its next number. */
export interface NumberDocument {
    id: string;
    requirement_id: string;
    requirement_name: string;
    filename: string;
    uploaded_at: string;
}

/** A number ordered while the carrier reviews what was filed for it: nothing is the account's, or charged, until it
 *  completes. `rejected`: sent back, with the carrier's `reason`, to correct and resubmit by `deadline`. */
export interface NumberOrder {
    id: string;
    phone_number: string;
    country: string;
    number_type: NumberType;
    status: 'in_review' | 'rejected' | 'completed' | 'failed';
    reason: string | null;
    deadline: string | null;
    monthly_usd: number;
    upfront_usd: number;
    credential_id: string | null;
    created_at: string;
    /** While it's open: what a resubmission answers. */
    requirements?: { needs: NumberNeeds; items: NumberRequirement[] };
}

export interface AvailableNumber {
    phone_number: string;
    country: string;
    number_type: NumberType;
    locality: string;
    region: string;
    capabilities: string[];
    /** Its price for this account, in dollars: each month, and once when it's bought. */
    monthly_usd: number;
    upfront_usd: number;
    /** What its country asks before it's sold. */
    requirements: { needs: NumberNeeds; items: NumberRequirement[] };
    /** registration: a US number, texting under a US carrier registration; unavailable: not from its country yet. */
    texting: 'registration' | 'unavailable' | 'none';
}

export interface CountryCoverage {
    country: string;
    /** The kinds in stock there. */
    number_types: NumberType[];
    texting_types: NumberType[];
    /** The kinds bought with documents the carrier reviews first. */
    documents_types: NumberType[];
    /** The kinds that ask a step that can't be taken here, so can't be bought here yet. */
    steps_types: NumberType[];
}

/** The kind to open a country on: ``preferred`` where it can be bought there, else the first kind that can, else
 *  ``preferred`` or the first kind sold (each asking a step). */
export function openingKind(sold: CountryCoverage | undefined, preferred: NumberType): NumberType {
    if (!sold) return preferred;
    const buyable = sold.number_types.filter((t) => !sold.steps_types.includes(t));
    if (buyable.includes(preferred)) return preferred;
    return buyable[0] ?? (sold.number_types.includes(preferred) ? preferred : (sold.number_types[0] ?? preferred));
}

/** A country's kinds as the country picker lists them: "Local, Mobile", the ones that need documents said so, and the
 *  ones that can't be bought here last, so the line says what can be bought before it runs out of room. */
export function coverageDetail(sold: CountryCoverage): string {
    const labels = (types: NumberType[]) => types.map((t) => TYPE_LABELS[t]);
    const buyable = sold.number_types.filter((t) => !sold.steps_types.includes(t));
    const docs = buyable.filter((t) => sold.documents_types.includes(t));
    const steps = labels(sold.number_types.filter((t) => sold.steps_types.includes(t)));
    const parts = [labels(buyable).join(', ')];
    if (docs.length) parts.push(docs.length === buyable.length ? 'needs documents' : `${labels(docs).join(', ')} ${docs.length > 1 ? 'need' : 'needs'} documents`);
    if (steps.length) parts.push(buyable.length ? `${steps.join(', ')} not sold here yet` : `${steps.join(', ')} · not sold here yet`);
    return parts.filter(Boolean).join(' · ');
}

export interface NumberPlace {
    kind: 'locality' | 'area_code';
    value: string;
    region: string;
}

/** Who a number is registered to: their name and address, where its country asks who holds it. */
export interface NumberHolder {
    name: string;
    business_name?: string | null;
    street: string;
    street2?: string | null;
    city: string;
    region?: string | null;
    postal_code: string;
    country: string;
    /** E.164, where its country asks for the holder's contact information (a requirement of kind `contact`). */
    phone?: string | null;
}

export interface PhonePurchaseQuote {
    id: string;
    phone_number: string;
    country: string;
    number_type: NumberType;
    locality?: string;
    region?: string;
    capabilities?: string[];
    requirements: AvailableNumber['requirements'];
    texting?: AvailableNumber['texting'];
    monthly_usd: number;
    upfront_usd: number;
    expires_at: string;
}

export interface PhonePurchaseError {
    text: string;
    /** gated | unavailable | credits (the account is short of funds) | price | address | requirements | document |
     *  steps | order, or absent for anything else. */
    kind?: string;
}

export interface NumberFilters {
    country: string;
    numberType: NumberType;
    /** A city, region or area code, as picked from the places or typed. */
    place: string;
    /** What the place is; a typed one is read as an area code when it's digits, a city otherwise. */
    placeKind: PlaceKind | null;
    /** Digits (or keypad letters, * for any digit) the number contains. */
    contains: string;
    features: NumberFeatures;
}

type Reply<T> = Partial<T> & { error?: string; kind?: string; status?: string; credential_id?: string; phone_number?: string; order_id?: string };

export const FIRST_PAGE = 10;
export const MORE_PAGE = 20;
// Where nothing says where the person is.
const DEFAULT_COUNTRY = 'US';

export function purchaseFailureText(reply: { error?: string; kind?: string }, fallback: string): string {
    switch (reply.kind) {
        case 'gated':
            return 'Phone numbers are not enabled on this account yet.';
        case 'unavailable':
            return 'Numbers cannot be bought on this instance.';
        default:
            return reply.error || fallback;
    }
}

/** What a search sends for ``filters``: a typed place that's all digits is an area code, anything else a city. */
export function searchQuery(filters: NumberFilters, limit: number) {
    const place = filters.place.trim();
    const kind: PlaceKind | null = place ? (filters.placeKind ?? (/^\d+$/.test(place) ? 'area_code' : 'locality')) : null;
    const contains = filters.contains.toUpperCase().replace(/[^0-9A-Z*]/g, '').slice(0, 10);
    return {
        country: filters.country,
        number_type: filters.numberType,
        area_code: kind === 'area_code' ? place : null,
        locality: kind === 'locality' ? place : null,
        region: kind === 'region' ? place : null,
        contains: contains || null,
        features: filters.features,
        limit,
    };
}

/** The filters a search can drop when it found nothing, most narrowing first. */
export function loosenings(filters: NumberFilters, coverage: CountryCoverage | undefined): { label: string; change: Partial<NumberFilters> }[] {
    const out: { label: string; change: Partial<NumberFilters> }[] = [];
    if (filters.contains) out.push({ label: 'Any digits', change: { contains: '' } });
    if (filters.place) out.push({ label: 'Anywhere in the country', change: { place: '', placeKind: null } });
    if (filters.features === 'voice_sms') out.push({ label: 'Calls only', change: { features: 'voice' } });
    for (const type of coverage?.number_types ?? []) {
        if (type !== filters.numberType) out.push({ label: `${TYPE_LABELS[type]} numbers`, change: { numberType: type } });
    }
    return out;
}

export const TYPE_LABELS: Record<NumberType, string> = {
    local: 'Local',
    mobile: 'Mobile',
    toll_free: 'Toll-free',
    national: 'National',
    shared_cost: 'Shared cost',
};

/** One step of a purchase as it goes to a transport, named by `event_name` (`phone_number:search`, `:buy`, …). */
/** A purchase NoClick holds for the account's owner (src/sdk/held.ts), and the number it buys. */
export interface HeldNumber {
    call: HeldCall;
    phoneNumber: string;
}

export type NumberPurchaseEvent = { event_name: string } & Record<string, unknown>;

/** Where a surface's purchase steps go, each answered with its reply, and what else only its host can do. */
export interface NumberPurchaseTransport {
    // Each step's reply has its own shape, which the hook reads as it sends it.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    send: (event: NumberPurchaseEvent) => Promise<any>;
    /** Sends a document's file to the place the `phone_number:document_upload` step answered (`path`): the document
     *  as filed, or why it wasn't. A surface that files no documents has none. */
    upload?: (path: string, file: File) => Promise<{ document?: NumberDocument; error?: string }>;
    /** Files a document in one step (the SDK's `PhoneNumber.uploadDocument`), in place of `document_upload` + `upload`. */
    uploadDocument?: (subject: { country: string; number_type: NumberType }, requirement: NumberRequirement, file: File) => Promise<NumberDocument>;
    /** False where the transport can't list the account's numbers in review or its kept documents: the page then offers
     *  only the documents uploaded while it's open. */
    readsKept?: boolean;
    /** Where an account short of funds adds some, linked beside that refusal; none where the host has no such page. */
    fundsHref?: string;
    /** Called once a number is the account's (a host with cached lists of what the account holds drops them). */
    onPurchased?: () => void;
}

/** What a purchase answers: the holder where its country asks who holds it, and the rest by requirement id. */
export interface NumberFiling {
    holder?: NumberHolder;
    answers?: RequirementAnswers;
}

export function usePhoneNumberPurchase({
    onCredentialCreated,
    onOrdered,
    transport,
    confirmation,
    country: openedOn,
    firstPage = FIRST_PAGE,
    filesDocuments = true,
    finding = true,
}: {
    onCredentialCreated: (credentialId: string, phoneNumber: string) => void;
    /** A number the carrier reviews first was ordered: it's the account's, and charged, once the review completes. */
    onOrdered?: (order: { order_id: string; phone_number: string }) => void;
    transport: NumberPurchaseTransport;
    /** The country to open on: where the person is, as far as the page knows (it may arrive after the first render).
     *  Without one it opens on the United States. */
    country?: string;
    confirmation?: {
        initialQuote?: PhonePurchaseQuote | null;
        onState: (state: { status: string; error?: string | null; phone_number?: string | null; order?: NumberOrder | null }) => void;
    };
    /** How many numbers the first search shows. */
    firstPage?: number;
    /** Whether this surface files the documents a country asks for; one that doesn't says where such a number is
     *  bought instead. */
    filesDocuments?: boolean;
    /** Whether it finds numbers as it opens (where numbers are sold, and a first search); not to correct an order. */
    finding?: boolean;
}) {
    const [coverage, setCoverage] = useState<CountryCoverage[] | null>(null);
    const [contactPhone, setContactPhone] = useState<string | null>(null);
    const [filters, setFiltersState] = useState<NumberFilters | null>(null);
    const [places, setPlaces] = useState<NumberPlace[]>([]);
    const [searched, setSearched] = useState<{ filters: NumberFilters; limit: number } | null>(null);
    const [numbers, setNumbers] = useState<AvailableNumber[] | null>(null);
    const [searching, setSearching] = useState(false);
    const [buying, setBuying] = useState<string | null>(null);
    const [error, setError] = useState<PhonePurchaseError | null>(null);
    const [quote, setQuote] = useState(confirmation?.initialQuote ?? null);
    const [documents, setDocuments] = useState<NumberDocument[] | null>(null);
    const [uploading, setUploading] = useState<string | null>(null);
    const [orders, setOrders] = useState<NumberOrder[]>([]);
    const [held, setHeld] = useState<HeldNumber[]>([]);
    const submitting = useRef(false);
    const transportRef = useRef(transport);
    useEffect(() => {
        transportRef.current = transport;
    }, [transport]);

    const failed = (reply: { error?: string; kind?: string }, fallback: string) =>
        setError({ text: purchaseFailureText(reply, fallback), kind: reply.kind });

    const search = useCallback(async (wanted: NumberFilters, limit: number) => {
        setSearching(true);
        setError(null);
        try {
            const reply: Reply<{ numbers: AvailableNumber[] }> = await transportRef.current.send({ event_name: 'phone_number:search', ...searchQuery(wanted, limit) });
            if (reply.error) {
                failed(reply, 'Could not search for numbers.');
                return;
            }
            setSearched({ filters: wanted, limit });
            setNumbers(reply.numbers ?? []);
        } catch (e) {
            setError({ text: e instanceof Error ? e.message : 'Could not search for numbers.' });
        } finally {
            setSearching(false);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Where numbers are for sale, once, with the account's own verified phone to offer as a holder's contact.
    useEffect(() => {
        if (!finding) return;
        let live = true;
        (async () => {
            try {
                const reply: Reply<{ countries: CountryCoverage[]; contact_phone: string | null }> = await transportRef.current.send({ event_name: 'phone_number:coverage' });
                if (!live) return;
                if (reply.error) {
                    failed(reply, 'Could not load where numbers are sold.');
                    return;
                }
                setCoverage(reply.countries ?? []);
                setContactPhone(reply.contact_phone ?? null);
            } catch (e) {
                if (live) setError({ text: e instanceof Error ? e.message : 'Could not load where numbers are sold.' });
            }
        })();
        return () => {
            live = false;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // The account's numbers the carrier is reviewing, or sent back. A purchase link's own order comes with its status.
    const loadOrders = useCallback(async () => {
        if (confirmation || !filesDocuments || transportRef.current.readsKept === false) return;
        try {
            const reply: Reply<{ orders: NumberOrder[] }> = await transportRef.current.send({ event_name: 'phone_number:orders' });
            if (!reply.error) setOrders(reply.orders ?? []);
        } catch (e) {
            console.warn('[numbers] orders failed:', e);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [filesDocuments]);
    useEffect(() => {
        void loadOrders();
    }, [loadOrders]);

    /** The account's documents, read once a number that asks for them is chosen. */
    const loadDocuments = useCallback(async () => {
        if (documents !== null || !filesDocuments) return;
        if (transportRef.current.readsKept === false) {
            setDocuments([]);
            return;
        }
        const reply: Reply<{ documents: NumberDocument[] }> = await transportRef.current.send({ event_name: 'phone_number:documents' });
        if (reply.error) failed(reply, 'Could not load your documents.');
        else setDocuments(reply.documents ?? []);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [documents, filesDocuments]);

    /** Upload ``file`` for ``requirement`` of ``subject``'s country: to the place the transport is told to send it. */
    const uploadDocument = async (subject: { country: string; number_type: NumberType }, requirement: NumberRequirement, file: File) => {
        setUploading(requirement.id);
        setError(null);
        try {
            const direct = transportRef.current.uploadDocument;
            if (direct) {
                const filed = await direct(subject, requirement, file);
                setDocuments((current) => [filed, ...(current ?? [])]);
                return filed;
            }
            const reply: Reply<{ upload_url_path: string }> = await transportRef.current.send({
                event_name: 'phone_number:document_upload',
                country: subject.country,
                number_type: subject.number_type,
                requirement_id: requirement.id,
            });
            if (reply.error || !reply.upload_url_path) {
                failed(reply, 'Could not start the upload.');
                return null;
            }
            const upload = transportRef.current.upload;
            if (!upload) throw new Error('Documents aren’t filed here.');
            const data = await upload(reply.upload_url_path, file);
            if (!data.document) {
                setError({ text: data.error || 'Could not upload that file.', kind: 'document' });
                return null;
            }
            const uploaded = data.document;
            setDocuments((current) => [uploaded, ...(current ?? [])]);
            return uploaded;
        } catch (e) {
            setError({ text: e instanceof Error ? e.message : 'Could not upload that file.', kind: 'document' });
            return null;
        } finally {
            setUploading(null);
        }
    };

    /** Remove one of the account's documents; whether the carrier keeps it on file for a number it was filed for. */
    const removeDocument = async (document: NumberDocument) => {
        const reply: Reply<{ kept_by_carrier: boolean }> = await transportRef.current.send({ event_name: 'phone_number:document_remove', document_id: document.id });
        if (reply.error) {
            failed(reply, 'Could not remove that document.');
            return null;
        }
        setDocuments((current) => current?.filter((d) => d.id !== document.id) ?? current);
        return { keptByCarrier: !!reply.kept_by_carrier };
    };

    // Open on the person's own country, with numbers to choose from rather than an empty search.
    useEffect(() => {
        if (!coverage || filters) return;
        const country = openedOn ?? DEFAULT_COUNTRY;
        const sold = coverage.find((c) => c.country === country);
        const start: NumberFilters = {
            country,
            numberType: openingKind(sold, 'local'),
            place: '',
            placeKind: null,
            contains: '',
            features: 'voice',
        };
        setFiltersState(start);
        if (sold) void search(start, firstPage);
    }, [coverage, openedOn, filters, firstPage, search]);

    const country = useMemo(() => coverage?.find((c) => c.country === filters?.country), [coverage, filters?.country]);

    // The places a country's numbers of a kind are for sale in, for the place field's suggestions.
    useEffect(() => {
        if (!filters || !country) return;
        let live = true;
        setPlaces([]);
        transportRef.current
            .send({ event_name: 'phone_number:places', country: filters.country, number_type: filters.numberType })
            .then((reply: Reply<{ places: NumberPlace[] }>) => {
                if (!live) return;
                if (reply.error) console.warn('[numbers] places failed:', reply.error);
                else setPlaces(reply.places ?? []);
            })
            // Suggestions only: the field still takes what's typed.
            .catch((err: unknown) => console.warn('[numbers] places failed:', err));
        return () => {
            live = false;
        };
    }, [filters?.country, filters?.numberType, country]); // eslint-disable-line react-hooks/exhaustive-deps

    /** Change the filters; ``run`` searches with them at once (a pick does, typing waits for the Search button). */
    const update = (change: Partial<NumberFilters>, run = true) => {
        if (!filters) return;
        let next = { ...filters, ...change };
        if (change.country && change.country !== filters.country) {
            const sold = coverage?.find((c) => c.country === change.country);
            next = { ...next, place: '', placeKind: null, numberType: openingKind(sold, next.numberType) };
        }
        if (change.numberType && change.numberType !== filters.numberType && change.place === undefined) next = { ...next, place: '', placeKind: null };
        setFiltersState(next);
        if (run && coverage?.some((c) => c.country === next.country)) void search(next, firstPage);
    };

    /** Buy ``number`` (or, on a confirmation link, quote it); whether it was bought, or ordered for the carrier's review. */
    const buy = async (number: AvailableNumber, filing: NumberFiling = {}): Promise<boolean> => {
        if (submitting.current) return false;
        submitting.current = true;
        setBuying(number.phone_number);
        setError(null);
        try {
            if (confirmation) {
                const reply: Reply<{ quote: PhonePurchaseQuote }> = await transportRef.current.send({
                    event_name: 'phone_number:quote',
                    phone_number: number.phone_number,
                    country: number.country,
                    number_type: number.number_type,
                });
                if (reply.error || !reply.quote) failed(reply, 'Could not prepare that number.');
                else setQuote(reply.quote);
                return false;
            }
            const reply: Reply<{ credential_id: string; phone_number: string; monthly_usd: number; upfront_usd: number }> = await transportRef.current.send({
                event_name: 'phone_number:buy',
                phone_number: number.phone_number,
                country: number.country,
                number_type: number.number_type,
                monthly_usd: number.monthly_usd,
                upfront_usd: number.upfront_usd,
                ...(filing.holder ? { holder: filing.holder } : {}),
                ...(filing.answers ? { answers: filing.answers } : {}),
            });
            if (!reply.error && reply.order_id) {
                // In the carrier's review: nothing is held or charged until it completes.
                setNumbers((current) => current?.filter((n) => n.phone_number !== number.phone_number) ?? current);
                onOrdered?.({ order_id: reply.order_id, phone_number: reply.phone_number ?? number.phone_number });
                void loadOrders();
                return true;
            }
            if (reply.error || !reply.credential_id) {
                if (reply.kind === 'price' && reply.monthly_usd !== undefined && reply.upfront_usd !== undefined) {
                    // Show the new price where the old one was; buying again agrees to it.
                    const moved = { monthly_usd: reply.monthly_usd, upfront_usd: reply.upfront_usd };
                    setNumbers((current) => current?.map((n) => (n.phone_number === number.phone_number ? { ...n, ...moved } : n)) ?? current);
                }
                failed(reply, 'Could not buy that number.');
                return false;
            }
            transportRef.current.onPurchased?.();
            onCredentialCreated(reply.credential_id, reply.phone_number ?? number.phone_number);
            return true;
        } catch (e) {
            const call = heldCallOf(e);
            if (call) {
                // Held for the account's owner: it's bought once they approve it, so it leaves the list meanwhile.
                setNumbers((current) => current?.filter((n) => n.phone_number !== number.phone_number) ?? current);
                setHeld((current) => [...current.filter((h) => h.call.approvalId !== call.approvalId), { call, phoneNumber: number.phone_number }]);
                return true;
            }
            setError({ text: e instanceof Error ? e.message : 'Could not buy that number.' });
            return false;
        } finally {
            submitting.current = false;
            setBuying(null);
        }
    };

    /** Where a held purchase ended: bought, as a purchase made at once is; anything else stays said on its notice. */
    const heldSettled = (number: HeldNumber, state: HeldState) => {
        if (state.phase !== 'done') return;
        const bought = (state.response ?? {}) as { id?: unknown; number?: unknown };
        setHeld((current) => current.filter((h) => h.call.approvalId !== number.call.approvalId));
        transportRef.current.onPurchased?.();
        onCredentialCreated(typeof bought.id === 'string' ? bought.id : '', typeof bought.number === 'string' ? bought.number : number.phoneNumber);
    };

    const confirm = async (filing: NumberFiling = {}) => {
        if (!quote || submitting.current || !confirmation) return;
        submitting.current = true;
        setBuying(quote.phone_number);
        setError(null);
        try {
            const reply: Reply<{ status: string; order: NumberOrder }> = await transportRef.current.send({
                event_name: 'phone_number:confirm',
                quote_id: quote.id,
                ...(filing.holder ? { holder: filing.holder } : {}),
                ...(filing.answers ? { answers: filing.answers } : {}),
            });
            if (reply.status === 'fulfilled' && reply.credential_id) {
                transportRef.current.onPurchased?.();
                onCredentialCreated(reply.credential_id, reply.phone_number ?? quote.phone_number);
            } else if (reply.status === 'provisioning' || reply.status === 'in_review' || reply.status === 'rejected') {
                confirmation.onState(reply as { status: string; error?: string | null; phone_number?: string | null; order?: NumberOrder | null });
            } else if (reply.kind === 'address' || reply.kind === 'requirements' || reply.kind === 'document') {
                // Nothing was claimed: the same quote stands once what's missing is added.
                setError({ text: purchaseFailureText(reply, 'Add what the number’s country asks to buy it.'), kind: reply.kind });
            } else {
                setQuote(null);
                setError({ text: purchaseFailureText(reply, 'Select the number again to review its current price.'), kind: reply.kind });
            }
        } catch {
            confirmation.onState({ status: 'provisioning', error: 'Connection interrupted. Check the request status before trying again.' });
        } finally {
            submitting.current = false;
            setBuying(null);
        }
    };

    /** File corrected answers for an order the carrier sent back (a purchase link's own, under ``confirmation``). */
    const resubmit = async (order: NumberOrder, filing: NumberFiling) => {
        if (submitting.current) return null;
        submitting.current = true;
        setBuying(order.phone_number);
        setError(null);
        try {
            const reply: Reply<{ order: NumberOrder; status: string }> = await transportRef.current.send({
                event_name: 'phone_number:resubmit',
                ...(confirmation ? {} : { order_id: order.id }),
                ...(filing.holder ? { holder: filing.holder } : {}),
                answers: filing.answers ?? {},
            });
            if (reply.error) {
                failed(reply, 'Could not resubmit it.');
                return null;
            }
            if (confirmation) confirmation.onState(reply as { status: string; order?: NumberOrder | null });
            else void loadOrders();
            return reply.order ?? null;
        } catch (e) {
            setError({ text: e instanceof Error ? e.message : 'Could not resubmit it.' });
            return null;
        } finally {
            submitting.current = false;
            setBuying(null);
        }
    };

    return {
        coverage,
        /** The country it was asked to open on. */
        openedOn,
        /** Where an account short of funds adds some (the transport's). */
        fundsHref: transport.fundsHref,
        /** The account's own verified phone, to prefill a holder's contact phone; null where there's none. */
        contactPhone,
        country,
        filters,
        places,
        update,
        numbers,
        searched,
        searching,
        buying,
        busy: searching || !!buying,
        error,
        quote,
        setQuote,
        /** The chosen country sells no numbers. */
        notSold: !!coverage && !!filters && !country,
        loosen: filters && numbers?.length === 0 ? loosenings(filters, country) : [],
        /** A first page came back full, so there may be more. */
        canShowMore: numbers !== null && searched !== null && searched.limit < MORE_PAGE && numbers.length >= searched.limit,
        search: () => (filters ? search(filters, firstPage) : Promise.resolve()),
        showMore: () => (searched ? search(searched.filters, MORE_PAGE) : Promise.resolve()),
        buy,
        confirm,
        /** Whether this surface files documents (a number asking for them is bought here). */
        filesDocuments,
        documents,
        loadDocuments,
        uploadDocument,
        /** The requirement a document is uploading for. */
        uploading,
        /** Null where the transport can't remove a document (the SDK's, today). */
        removeDocument: transport.readsKept === false ? null : removeDocument,
        orders,
        resubmit,
        /** Purchases waiting on the account's owner, each followed where it's shown until it's bought or not. */
        held,
        heldSettled,
    };
}

export type PhoneNumberPurchase = ReturnType<typeof usePhoneNumberPurchase>;
