// The number purchase flow (usePhoneNumberPurchase) over /v1 through the SDK's `PhoneNumber` and `PhoneNumberOrder`:
// prices are the API's own dollars, a purchase's ceilings exactly the prices the row showed, a country's documents
// uploaded and named in its requirements, and a number its carrier reviews followed as an order. The console and the
// hosted app's number pages (Resources' Buy a number, the Phone step's form) buy through it.
import { PaymentRequired, PhoneNumber, PhoneNumberOrder, PriceExceeded } from 'noclick';
import type { AvailableNumber, NoClick, PhoneNumberType } from 'noclick';
import type { NumberDocument, NumberHolder, NumberOrder, NumberPurchaseTransport } from './usePhoneNumberPurchase';

/** Who a purchase is for: one of the account's users (null: the account), and what its code calls the number. */
export interface NumberBuyer {
    user: string | null;
    name: string;
}

/** The flow's transport over `client` (asked for at each step), buying for `buyer()` as it stands then. */
export function sdkNumberTransport(
    client: () => Promise<NoClick>,
    buyer: () => NumberBuyer,
    { fundsHref, onPurchased }: { fundsHref?: string; onPurchased?: () => void } = {}
): NumberPurchaseTransport {
    const send: NumberPurchaseTransport['send'] = async (event) => {
        const api = await client();
        if (event.event_name === 'phone_number:coverage') {
            const countries = await PhoneNumber.coverage({ client: api, user: null });
            return {
                countries: countries.map((c) => ({
                    country: c.country,
                    number_types: c.types,
                    texting_types: c.textingTypes,
                    documents_types: c.documentsTypes,
                    steps_types: c.stepsTypes,
                })),
                contact_phone: null,
            };
        }
        if (event.event_name === 'phone_number:places') {
            return { places: await PhoneNumber.places(event.country as string, { client: api, user: null, type: event.number_type as PhoneNumberType }) };
        }
        if (event.event_name === 'phone_number:search') {
            const found = await PhoneNumber.available({
                client: api,
                user: null,
                country: event.country as string,
                type: event.number_type as PhoneNumberType,
                areaCode: (event.area_code as string | null) ?? undefined,
                locality: (event.locality as string | null) ?? undefined,
                region: (event.region as string | null) ?? undefined,
                contains: (event.contains as string | null) ?? undefined,
                features: event.features as 'voice' | 'voice_sms',
                limit: event.limit as number,
            });
            return { numbers: found.map(offerOf) };
        }
        if (event.event_name === 'phone_number:buy') {
            const { user, name } = buyer();
            let number: PhoneNumber | PhoneNumberOrder;
            try {
                number = await PhoneNumber.buy(event.phone_number as string, {
                    client: api,
                    user,
                    country: event.country as string,
                    type: event.number_type as PhoneNumberType,
                    maxMonthlyUsd: event.monthly_usd as number,
                    maxUpfrontUsd: event.upfront_usd as number,
                    address: holderOf(event.holder as NumberHolder | undefined),
                    requirements: event.answers as Record<string, string> | undefined,
                    name: name.trim() || undefined,
                });
            } catch (error) {
                // Its price moved since the row showed it: the refusal names both prices as they stand, which the
                // flow shows in the row; buying again agrees to them.
                if (error instanceof PriceExceeded) {
                    const { monthly_usd, upfront_usd } = error.details;
                    return { error: 'This number’s price changed since it was shown. Review the new price and buy it again.', kind: 'price', monthly_usd, upfront_usd };
                }
                // Short of the funds a number needs: the flow offers the way to add some.
                if (error instanceof PaymentRequired) return { error: error.message, kind: 'credits' };
                throw error;
            }
            // A number whose country asks for documents waits on the carrier's review: nothing is held until then.
            if (!(number instanceof PhoneNumber)) return { order_id: number.id, phone_number: number.number };
            if (!number.credentialId) throw new Error(`${number.number} was bought, but no account holds it for a Phone step.`);
            return { credential_id: number.credentialId, phone_number: number.number };
        }
        if (event.event_name === 'phone_number:orders') {
            return { orders: (await PhoneNumberOrder.list({ client: api, user: buyer().user })).map(orderOf) };
        }
        if (event.event_name === 'phone_number:resubmit') {
            const order = await PhoneNumberOrder.retrieve(event.order_id as string, { client: api, user: buyer().user });
            await order.resubmit({
                address: holderOf(event.holder as NumberHolder | undefined),
                requirements: event.answers as Record<string, string> | undefined,
            });
            return { order: orderOf(order), status: order.status };
        }
        if (event.event_name === 'phone_number:documents') {
            return { documents: (await PhoneNumber.documents({ client: api, user: null })).map((d) => d.raw as unknown as NumberDocument) };
        }
        if (event.event_name === 'phone_number:document_upload') {
            // The upload itself is the SDK's (`upload` below): what it's for travels as the step's "path".
            return { upload_url_path: JSON.stringify({ country: event.country, type: event.number_type, requirement: event.requirement_id }) };
        }
        if (event.event_name === 'phone_number:document_remove') {
            return { kept_by_carrier: (await PhoneNumber.removeDocument(event.document_id as string, { client: api, user: null })).keptByCarrier };
        }
        throw new Error(`Numbers bought over /v1 have no step ${event.event_name}.`);
    };
    const upload: NonNullable<NumberPurchaseTransport['upload']> = async (path, file) => {
        const subject = JSON.parse(path) as { country: string; type: PhoneNumberType; requirement: string };
        try {
            const document = await PhoneNumber.uploadDocument(file, { client: await client(), user: null, filename: file.name, ...subject });
            return { document: document.raw as unknown as NumberDocument };
        } catch (error) {
            return { error: error instanceof Error ? error.message : 'Could not upload that file.' };
        }
    };
    return { send, upload, fundsHref, onPurchased };
}

/** The holder a purchase files, in the SDK's words. */
function holderOf(holder: NumberHolder | undefined) {
    return holder && {
        name: holder.name,
        businessName: holder.business_name ?? undefined,
        street: holder.street,
        street2: holder.street2 ?? undefined,
        city: holder.city,
        region: holder.region ?? undefined,
        postalCode: holder.postal_code,
        country: holder.country,
        phone: holder.phone ?? undefined,
    };
}

/** An order as the purchase flow lists it. */
function orderOf(order: PhoneNumberOrder): NumberOrder {
    return {
        id: order.id,
        phone_number: order.number,
        country: order.country ?? '',
        number_type: (order.type ?? 'local') as NumberOrder['number_type'],
        status: order.status,
        reason: order.reason,
        deadline: order.deadline?.toISOString() ?? null,
        monthly_usd: order.monthlyUsd ?? 0,
        upfront_usd: order.upfrontUsd ?? 0,
        credential_id: order.phoneNumberId,
        created_at: order.createdAt?.toISOString() ?? '',
        requirements: (order.requirements ?? undefined) as NumberOrder['requirements'],
    };
}

function offerOf(n: AvailableNumber) {
    return {
        phone_number: n.number,
        country: n.country,
        number_type: n.type,
        locality: n.locality ?? '',
        region: n.region ?? '',
        capabilities: n.capabilities,
        monthly_usd: n.monthlyUsd ?? 0,
        upfront_usd: n.upfrontUsd ?? 0,
        requirements: n.requirements,
        texting: n.texting,
    };
}
