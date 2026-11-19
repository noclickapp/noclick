// Resources' domain registrar on the platform API: a search is GET
// /v1/domains/search for the name on every ending Resources offers (the asked
// one first) and the registrar's close names; checking out reads the
// registration agreement and the account's registrant on file, or with nobody
// on file what NoClick knows of its owner (GET /v1/account); a purchase is
// POST /v1/domains for the account itself, at the offer's term, ceilinged at
// the price the buyer saw, with the registrant and the trademark notice's
// acceptance when the buyer gave them; `onPurchase` hears its operation's id.
import { DomainRegistrarError, type DomainOffer, type DomainRegistrar, type DomainSearch } from '@/screens/domains/useDomainPurchase';
import type { KnownRegistrant } from '@/lib/domainRegistrant';
import { formatPrice as formatDollars } from '@/screens/numbers/numberDisplay';
import { Domain, NoClickError, type DomainOffer as PlatformOffer, type NoClick } from 'noclick';

/** The endings Resources searches, most wanted first. */
export const DOMAIN_ENDINGS = ['com', 'ai', 'io', 'co', 'app', 'dev', 'net', 'org'];
/** The exact names first (one per ending), then the registrar's suggestions. */
const SEARCH_LIMIT = 20;
const CLOSE_NAMES = 4;

const ending = (domain: string) => domain.slice(domain.indexOf('.') + 1);

function toOffer(found: PlatformOffer, close: boolean): DomainOffer | null {
    if (!found.available || found.priceUsd == null) return null;
    return {
        domain: found.name,
        ending: ending(found.name),
        priceUsd: found.priceUsd,
        years: found.minYears ?? 1,
        renewalUsd: found.renewalUsd,
        ...(close ? { close } : {}),
        ...(found.premium ? { premium: true } : {}),
        ...(found.claimsNotice ? { claimsNotice: found.claimsNotice } : {}),
    };
}

/** The API's refusal in the page's terms: what lifts it (funds, on any plan), or that this deployment sells no domains. */
function refusal(error: unknown, offer?: DomainOffer): Error {
    if (!(error instanceof NoClickError)) return error instanceof Error ? error : new Error(String(error));
    const said = error.nextStep ? `${error.message} ${error.nextStep}` : error.message;
    switch (error.type) {
        case 'payment_required':
            return new DomainRegistrarError(said, 'credits');
        case 'price_exceeded': {
            const now = typeof error.details.price_usd === 'number' ? ` now costs ${formatDollars(error.details.price_usd)},` : ' costs';
            return new DomainRegistrarError(`${offer?.domain ?? 'It'}${now} more than the price you saw. Search again to see the new price.`);
        }
        case 'not_available':
            // Before a purchase, only a deployment that holds no registrar answers this; a purchase's is about the name.
            return new DomainRegistrarError(said, offer ? undefined : 'unavailable');
        default:
            return new DomainRegistrarError(said);
    }
}

export function platformRegistrar(client: NoClick, { onPurchase }: { onPurchase?: (operationId: string) => void } = {}): DomainRegistrar {
    return {
        endings: DOMAIN_ENDINGS,

        async search({ name, ending: asked }): Promise<DomainSearch> {
            const wanted = asked ?? DOMAIN_ENDINGS[0];
            const tlds = [wanted, ...DOMAIN_ENDINGS.filter((e) => e !== wanted)];
            let found: PlatformOffer[];
            try {
                found = await Domain.search(name, { client, user: null, tlds, limit: SEARCH_LIMIT });
            } catch (error) {
                throw refusal(error);
            }
            const exact = (f: PlatformOffer) => f.name.slice(0, f.name.indexOf('.')) === name && tlds.includes(ending(f.name));
            const exactOffers = found
                .filter(exact)
                .sort((a, b) => tlds.indexOf(ending(a.name)) - tlds.indexOf(ending(b.name)))
                .map((f) => toOffer(f, false));
            const closeOffers = found
                .filter((f) => !exact(f))
                .map((f) => toOffer(f, true))
                .filter((o): o is DomainOffer => o !== null)
                .slice(0, CLOSE_NAMES);
            const domain = `${name}.${wanted}`;
            const askedFor = found.find((f) => f.name === domain);
            const status = askedFor?.available ? 'available' : askedFor && DOMAIN_ENDINGS.includes(wanted) ? 'taken' : 'unavailable';
            return { asked: { domain, status }, offers: [...exactOffers.filter((o): o is DomainOffer => o !== null), ...closeOffers] };
        },

        async checkout() {
            try {
                const [agreement, onFile] = await Promise.all([Domain.agreement({ client }), Domain.defaultRegistrant({ client })]);
                // A registrant on file that never accepted the agreement can't register anything: ask for details instead.
                const usable = onFile?.agreementAcceptedAt ? onFile : null;
                if (usable) {
                    return {
                        agreementUrl: agreement.url,
                        onFile: { name: usable.name, email: usable.email, ...(usable.organization ? { organization: usable.organization } : {}) },
                    };
                }
                const { owner } = await client.request<{ owner: KnownRegistrant }>('GET', '/v1/account', { user: null });
                return { agreementUrl: agreement.url, onFile: null, known: owner };
            } catch (error) {
                throw refusal(error);
            }
        },

        async buy(offer, { registrant, acceptClaims }) {
            let purchase;
            try {
                purchase = await Domain.buy(offer.domain, { client, user: null, maxPriceUsd: offer.priceUsd, years: offer.years, registrant, acceptClaims });
            } catch (error) {
                throw refusal(error, offer);
            }
            onPurchase?.(purchase.id);
        },
    };
}
