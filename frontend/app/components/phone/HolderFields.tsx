// The holder's name and address, and a phone to reach them on where their country asks for one, for a number whose
// country asks who holds it. Fields under their labels, standing on their own; the country is the number's.
import { useEffect, useId, useState } from 'react';
import { parsePhoneNumberFromString } from 'libphonenumber-js';
import { FIELD, FIELD_LABEL } from '~/components/shell/fields';
import { countryName } from '~/components/ui/country-picker';
import { PhoneNumberInput } from '~/components/ui/phone-number-input';
import type { NumberHolder } from '~/hooks/usePhoneNumberPurchase';
import { cn } from '~/lib/utils';

export function emptyHolder(country: string, phone: string | null = null): NumberHolder {
    return { name: '', business_name: '', street: '', street2: '', city: '', region: '', postal_code: '', country, phone: phone ?? '' };
}

/** The holder a form edits, its phone prefilled with `contactPhone` (the account's own verified phone) once it's known. */
export function useHolder(country: string, contactPhone: string | null) {
    const [holder, setHolder] = useState(() => emptyHolder(country, contactPhone));
    useEffect(() => {
        if (contactPhone) setHolder((current) => (current.phone ? current : { ...current, phone: contactPhone }));
    }, [contactPhone]);
    return [holder, setHolder] as const;
}

/** The holder as a purchase sends it: blanks dropped, and the phone only where the number's country asks for one. */
export function holderToSend(holder: NumberHolder, askPhone: boolean): NumberHolder {
    const blank = (v: string | null | undefined) => (v && v.trim() ? v.trim() : null);
    return {
        name: holder.name.trim(), business_name: blank(holder.business_name), street: holder.street.trim(), street2: blank(holder.street2),
        city: holder.city.trim(), region: blank(holder.region), postal_code: holder.postal_code.trim(), country: holder.country,
        ...(askPhone ? { phone: blank(holder.phone) } : {}),
    };
}

/** What's missing before it can be sent; empty when it's complete. */
export function holderMissing(holder: NumberHolder, askPhone: boolean): string[] {
    const missing: string[] = [];
    if (!/\S+\s+\S+/.test(holder.name)) missing.push('first and last name');
    if (askPhone && !parsePhoneNumberFromString(holder.phone ?? '')?.isValid()) missing.push('contact phone');
    if (!holder.street.trim()) missing.push('street');
    if (!holder.city.trim()) missing.push('city');
    if (!holder.postal_code.trim()) missing.push('postal code');
    return missing;
}

export function HolderFields({
    holder,
    onChange,
    askPhone = false,
    disabled,
}: {
    holder: NumberHolder;
    onChange: (next: NumberHolder) => void;
    /** The number's country asks for the holder's contact information: a phone to reach them on as well. */
    askPhone?: boolean;
    disabled?: boolean;
}) {
    const id = useId();
    const field = (key: keyof NumberHolder, label: string, options: { placeholder?: string; autoComplete?: string; className?: string } = {}) => (
        <div className={options.className}>
            <label htmlFor={`${id}-${key}`} className={FIELD_LABEL}>
                {label}
            </label>
            <input
                id={`${id}-${key}`}
                value={holder[key] ?? ''}
                onChange={(e) => onChange({ ...holder, [key]: e.target.value })}
                placeholder={options.placeholder}
                autoComplete={options.autoComplete}
                disabled={disabled}
                className={FIELD}
            />
        </div>
    );
    return (
        <div className="grid grid-cols-1 gap-x-4 gap-y-3.5 sm:grid-cols-2" data-testid="holder-fields">
            {field('name', 'Full name', { autoComplete: 'name', placeholder: 'First and last name' })}
            {field('business_name', 'Business (optional)', { autoComplete: 'organization' })}
            {askPhone && (
                <div className="sm:col-span-2">
                    <label htmlFor={`${id}-phone`} className={FIELD_LABEL}>
                        Contact phone
                    </label>
                    <PhoneNumberInput
                        id={`${id}-phone`}
                        name="contact_phone"
                        value={holder.phone ?? ''}
                        onChange={(phone) => onChange({ ...holder, phone })}
                        disabled={disabled}
                        className="h-10"
                    />
                </div>
            )}
            {field('street', 'Street address', { autoComplete: 'address-line1', className: 'sm:col-span-2' })}
            {field('street2', 'Apartment, suite (optional)', { autoComplete: 'address-line2', className: 'sm:col-span-2' })}
            {field('city', 'City', { autoComplete: 'address-level2' })}
            {field('region', 'State, province or county (optional)', { autoComplete: 'address-level1' })}
            {field('postal_code', 'Postal code', { autoComplete: 'postal-code' })}
            <div>
                <span className={FIELD_LABEL}>Country</span>
                <p className={cn(FIELD, 'flex items-center text-muted-foreground')}>{countryName(holder.country)}</p>
            </div>
        </div>
    );
}
