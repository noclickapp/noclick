// Phone number entry: a searchable country picker beside a field that formats
// as people type (libphonenumber-js). Digits typed without a + get the picked
// country's calling code; typing +<code> moves the picker to that country. The
// value is E.164, what every backend phone seam takes, on a hidden input `name`.
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
    AsYouType,
    getCountries,
    getCountryCallingCode,
    getExampleNumber,
    type CountryCode,
} from 'libphonenumber-js';
import examples from 'libphonenumber-js/mobile/examples';
import metadata from 'libphonenumber-js/min/metadata';
import { ChevronDown } from 'lucide-react';
import {
    CountryFlag,
    CountryPicker,
    countryName,
    type CountryOption,
} from '~/components/ui/country-picker';
import { useDetectedCountry } from '~/hooks/useDetectedCountry';
import { cn } from '~/lib/utils';

interface PhoneNumberInputProps {
    name: string;
    id?: string;
    disabled?: boolean;
    className?: string;
    /** Controlled use: the E.164 value and its setter. */
    value?: string;
    onChange?: (e164: string) => void;
}

interface Formatted {
    text: string;
    e164: string;
    callingCode?: string;
    country?: CountryCode;
}

const COUNTRIES: CountryOption[] = getCountries().map((code) => {
    const callingCode = getCountryCallingCode(code);
    return { code, detail: `+${callingCode}`, keywords: [callingCode] };
});

// The main country of a calling code shared by several (+1 → US, +44 → GB).
function mainCountry(callingCode: string): CountryCode | undefined {
    return (metadata.country_calling_codes as Record<string, CountryCode[]>)[
        callingCode
    ]?.[0];
}

const digitsOf = (text: string) => text.replace(/[^\d+]/g, '');

/** What the field shows for `raw`, reading it against `country` when it has no +. */
export function formatPhone(raw: string, country?: CountryCode): Formatted {
    let text = raw.replace(/[^\d+]/g, '');
    if (!text) return { text: '', e164: '' };
    if (!text.startsWith('+')) {
        // A national number: its leading trunk 0 goes when the code goes on.
        text = country
            ? `+${getCountryCallingCode(country)}${text.replace(/^0+/, '')}`
            : `+${text}`;
    }
    text = `+${text.slice(1).replace(/\+/g, '')}`;
    const typer = new AsYouType();
    const shown = typer.input(text);
    const callingCode = typer.getCallingCode();
    return {
        text: shown,
        e164: typer.getNumber()?.number ?? '',
        callingCode,
        country:
            typer.getCountry() ??
            (callingCode ? mainCountry(callingCode) : undefined),
    };
}

export function PhoneNumberInput({
    name,
    id,
    disabled,
    className,
    value,
    onChange,
}: PhoneNumberInputProps) {
    const detected = useDetectedCountry();
    const [country, setCountry] = useState<CountryCode | undefined>(detected);
    const [picked, setPicked] = useState(false);
    const [field, setField] = useState<Formatted>({ text: '', e164: '' });
    const inputRef = useRef<HTMLInputElement>(null);

    // Detection lands after mount; it never overrides a country the person chose.
    useEffect(() => {
        if (!picked && !field.text && detected) setCountry(detected);
    }, [detected, picked, field.text]);

    // A controlled parent clearing its value (e.g. after linking) clears the field.
    useEffect(() => {
        if (value === '' && field.e164) setField({ text: '', e164: '' });
    }, [value, field.e164]);

    // One it sets to another number (a prefill) shows that number.
    useEffect(() => {
        if (!value || value === field.e164) return;
        const given = formatPhone(value);
        setField(given);
        if (given.country) setCountry(given.country);
    }, [value]); // eslint-disable-line react-hooks/exhaustive-deps

    const commit = (next: Formatted) => {
        setField(next);
        onChange?.(next.e164);
    };

    // Where the caret belongs after a reformat: after the same count of digits.
    const caretDigits = useRef<number | null>(null);
    useLayoutEffect(() => {
        const input = inputRef.current;
        if (caretDigits.current === null || !input) return;
        let seen = 0;
        let at = 0;
        while (at < field.text.length && seen < caretDigits.current) {
            if (/[\d+]/.test(field.text[at])) seen++;
            at++;
        }
        input.setSelectionRange(at, at);
        caretDigits.current = null;
    }, [field.text]);

    const type = (raw: string, caret: number) => {
        let text = raw;
        let before = raw.slice(0, caret);
        if (
            raw.length < field.text.length &&
            digitsOf(raw) === digitsOf(field.text)
        ) {
            // Backspace over a formatting space: take the digit before it instead.
            before = before.replace(/\d(?=\D*$)/, '');
            text = before + raw.slice(caret);
        }
        const next = formatPhone(text, country);
        // A + number keeps its digits, so the caret keeps its place among them;
        // a first keystroke or paste gains a calling code and the caret ends up last.
        caretDigits.current = text.startsWith('+')
            ? digitsOf(before).length
            : null;
        commit(next);
        // Keep the picker on a country that shares the typed code (+1 CA stays CA).
        if (next.callingCode && next.country && next.country !== country) {
            const same =
                country && getCountryCallingCode(country) === next.callingCode;
            if (!same || next.country !== mainCountry(next.callingCode))
                setCountry(next.country);
        }
    };

    const pick = (code: CountryCode) => {
        setCountry(code);
        setPicked(true);
        if (field.text) {
            const national = new AsYouType();
            national.input(field.text);
            commit(
                formatPhone(
                    `+${getCountryCallingCode(code)}${national.getNationalNumber()}`
                )
            );
        }
        requestAnimationFrame(() => inputRef.current?.focus());
    };

    const placeholder = useMemo(() => {
        if (!country) return '+1 555 000 0000';
        return (
            getExampleNumber(country, examples)?.formatInternational() ??
            `+${getCountryCallingCode(country)}`
        );
    }, [country]);

    return (
        <div
            className={cn(
                'flex h-11 w-full items-center rounded-xl border border-input bg-background text-sm text-foreground transition-colors focus-within:border-muted-foreground/40',
                disabled && 'opacity-60',
                className
            )}
        >
            <CountryPicker
                value={country}
                options={COUNTRIES}
                detailBeside
                onPick={(code) => pick(code as CountryCode)}
                disabled={disabled}
                // Above the auth modal (z-[100]) this picker can sit inside.
                zIndexClassName="z-[120]"
                trigger={
                    <button
                        type="button"
                        disabled={disabled}
                        aria-label={
                            country
                                ? `Country: ${countryName(country)}`
                                : 'Choose a country'
                        }
                        className="flex h-full shrink-0 items-center gap-2 rounded-l-xl pl-4 pr-3 outline-none transition-colors hover:bg-foreground/[0.04] focus-visible:bg-foreground/[0.06]"
                    >
                        <CountryFlag country={country} />
                        <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                    </button>
                }
            />
            <span aria-hidden className="h-5 w-px shrink-0 bg-border" />
            <input
                ref={inputRef}
                id={id}
                type="tel"
                inputMode="tel"
                autoComplete="tel"
                disabled={disabled}
                value={field.text}
                onChange={(e) =>
                    type(
                        e.target.value,
                        e.target.selectionStart ?? e.target.value.length
                    )
                }
                placeholder={placeholder}
                className="h-full w-full min-w-0 rounded-r-xl bg-transparent px-3 text-[15px] outline-none placeholder:text-muted-foreground"
            />
            <input type="hidden" name={name} value={field.e164} />
        </div>
    );
}
