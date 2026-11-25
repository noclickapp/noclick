// The number finder's transport over ``/v1`` (the SDK's ``PhoneNumber``): the console's Buy a number and the open app's
// Resources, beside the finder it serves.
import { PhoneNumber, type AvailableNumber, type NoClick, type PhoneNumberType } from 'noclick';
import type { NumberHolder, NumberPurchaseTransport } from '@/screens/numbers/usePhoneNumberPurchase';

/** The shared number purchase flow (``usePhoneNumberPurchase``) over ``/v1``: prices are the API's own dollars, and a
 *  purchase's ceilings are exactly the prices the row showed. `buyer` is read as each purchase is made (whose the number
 *  is, and what the code calls it). It reads no kept orders or documents: the API has none to read yet. */
export function sdkNumberTransport(client: NoClick, buyer: () => { user: string | null; name: string }, fundsHref?: string): NumberPurchaseTransport {
    const send: NumberPurchaseTransport['send'] = async (event) => {
        if (event.event_name === 'phone_number:coverage') {
            const countries = await PhoneNumber.coverage({ client, user: null });
            return {
                countries: countries.map((c) => ({
                    country: c.country,
                    number_types: c.types,
                    texting_types: c.textingTypes,
                    documents_types: c.documentsTypes,
                    steps_types: c.stepsTypes,
                })),
            };
        }
        if (event.event_name === 'phone_number:places') {
            return { places: await PhoneNumber.places(event.country as string, { client, user: null, type: event.number_type as PhoneNumberType }) };
        }
        if (event.event_name === 'phone_number:search') {
            const found = await PhoneNumber.available({
                client,
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
            const holder = event.holder as NumberHolder | undefined;
            const { user, name } = buyer();
            const number = await PhoneNumber.buy(event.phone_number as string, {
                client,
                user,
                country: event.country as string,
                type: event.number_type as PhoneNumberType,
                maxMonthlyUsd: event.monthly_usd as number,
                maxUpfrontUsd: event.upfront_usd as number,
                address: holder && {
                    name: holder.name,
                    businessName: holder.business_name ?? undefined,
                    street: holder.street,
                    street2: holder.street2 ?? undefined,
                    city: holder.city,
                    region: holder.region ?? undefined,
                    postalCode: holder.postal_code,
                    country: holder.country,
                    phone: holder.phone ?? undefined,
                },
                requirements: (event.answers as Record<string, string> | undefined) ?? undefined,
                name: name.trim() || undefined,
            });
            // A number whose documents the carrier reviews first is an order until the review completes.
            if (!(number instanceof PhoneNumber)) return { order_id: number.id, phone_number: number.number };
            return { credential_id: number.id, phone_number: number.number };
        }
        throw new Error(`No /v1 call answers ${event.event_name}.`);
    };
    // A document goes to the carrier in one call.
    const uploadDocument: NonNullable<NumberPurchaseTransport['uploadDocument']> = async (subject, requirement, file) => {
        const filed = await PhoneNumber.uploadDocument(file, {
            client, user: buyer().user, requirement: requirement.id, country: subject.country,
            type: subject.number_type as PhoneNumberType, filename: file.name,
        });
        return {
            id: filed.id, requirement_id: filed.requirementId, requirement_name: filed.requirementName, filename: filed.filename,
            uploaded_at: filed.uploadedAt?.toISOString() ?? new Date().toISOString(),
        };
    };
    return { send, uploadDocument, readsKept: false, fundsHref };
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

