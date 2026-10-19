// Who a domain is registered to: the details ICANN requires of a registrant,
// the fields a form asks for them in, and when a draft of them is complete.
// One definition for every surface that buys a domain (Resources' buy page,
// the developer console's dialogs).

/** The person a domain is registered to (the platform SDK's `DomainContact`). */
export interface RegistrantContact {
    name: string;
    email: string;
    /** E.164, like `+14155550123`. */
    phone: string;
    /** A second street line follows a newline. */
    address: string;
    city: string;
    postalCode: string;
    /** Two letters, like `US`. */
    country: string;
    region: string;
    /** When set, that organization is the domain's legal owner. */
    organization?: string;
    /** When they accepted the domain registration agreement: nothing is registered without it. */
    agreementAcceptedAt?: Date;
}

export type RegistrantDraft = Record<Exclude<keyof RegistrantContact, 'agreementAcceptedAt'>, string>;

export const EMPTY_REGISTRANT: RegistrantDraft = { name: '', email: '', phone: '', address: '', city: '', region: '', postalCode: '', country: '', organization: '' };

export interface RegistrantField {
    key: keyof RegistrantDraft;
    label: string;
    placeholder: string;
    autoComplete: string;
    optional?: boolean;
    /** Spans the form's two columns. */
    wide?: boolean;
}

export const REGISTRANT_FIELDS: readonly RegistrantField[] = [
    { key: 'name', label: 'Full name', placeholder: 'Ana Silva', autoComplete: 'name' },
    { key: 'organization', label: 'Organization (optional)', placeholder: 'Acme Corp', autoComplete: 'organization', optional: true },
    { key: 'email', label: 'Email', placeholder: 'ana@example.com', autoComplete: 'email' },
    { key: 'phone', label: 'Phone', placeholder: '+14155550123', autoComplete: 'tel' },
    { key: 'address', label: 'Street address', placeholder: '500 Market St', autoComplete: 'street-address', wide: true },
    { key: 'city', label: 'City', placeholder: 'San Francisco', autoComplete: 'address-level2' },
    { key: 'region', label: 'State or region', placeholder: 'CA', autoComplete: 'address-level1' },
    { key: 'postalCode', label: 'Postal code', placeholder: '94105', autoComplete: 'postal-code' },
    { key: 'country', label: 'Country (two letters)', placeholder: 'US', autoComplete: 'country' },
];

/** The draft as a contact, or null until every required field is filled and the country is two letters. */
export function registrantFrom(draft: RegistrantDraft): Omit<RegistrantContact, 'agreementAcceptedAt'> | null {
    const complete = REGISTRANT_FIELDS.every((f) => f.optional || draft[f.key].trim());
    if (!complete || !/^[A-Za-z]{2}$/.test(draft.country.trim())) return null;
    return {
        name: draft.name.trim(),
        email: draft.email.trim(),
        phone: draft.phone.trim(),
        address: draft.address.trim(),
        city: draft.city.trim(),
        postalCode: draft.postalCode.trim(),
        country: draft.country.trim().toUpperCase(),
        region: draft.region.trim(),
        organization: draft.organization.trim() || undefined,
    };
}
