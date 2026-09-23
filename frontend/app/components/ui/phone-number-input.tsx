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
import * as Flags from 'country-flag-icons/react/3x2';
import { Check, ChevronDown, Globe, Search } from 'lucide-react';
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from '~/components/ui/popover';
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

const regionNames =
    typeof Intl !== 'undefined' && 'DisplayNames' in Intl
        ? new Intl.DisplayNames(['en'], { type: 'region' })
        : null;

const COUNTRIES = getCountries()
    .map((code) => ({
        code,
        name: regionNames?.of(code) ?? code,
        callingCode: getCountryCallingCode(code),
    }))
    .sort((a, b) => a.name.localeCompare(b.name));

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

function Flag({
    country,
    className,
}: {
    country?: CountryCode;
    className?: string;
}) {
    const Icon = country
        ? (Flags as Record<string, typeof Flags.US>)[country]
        : undefined;
    if (!Icon)
        return (
            <Globe className={cn('h-4 w-5 text-muted-foreground', className)} />
        );
    return (
        <Icon
            title=""
            className={cn('h-4 w-6 rounded-[2px] object-cover', className)}
        />
    );
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
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState('');
    const inputRef = useRef<HTMLInputElement>(null);

    // Detection lands after mount; it never overrides a country the person chose.
    useEffect(() => {
        if (!picked && !field.text && detected) setCountry(detected);
    }, [detected, picked, field.text]);

    // A controlled parent clearing its value (e.g. after linking) clears the field.
    useEffect(() => {
        if (value === '' && field.e164) setField({ text: '', e164: '' });
    }, [value, field.e164]);

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
        setOpen(false);
        setQuery('');
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

    const matches = useMemo(() => {
        const q = query.trim().toLowerCase().replace(/^\+/, '');
        if (!q) {
            // The current country first, so the list opens on it.
            const current = COUNTRIES.find((c) => c.code === country);
            return current
                ? [current, ...COUNTRIES.filter((c) => c !== current)]
                : COUNTRIES;
        }
        return COUNTRIES.filter(
            (c) =>
                c.name.toLowerCase().includes(q) ||
                c.code.toLowerCase() === q ||
                c.callingCode.startsWith(q)
        );
    }, [query, country]);

    return (
        <div
            className={cn(
                'flex h-11 w-full items-center rounded-xl border border-input bg-background text-sm text-foreground transition-colors focus-within:border-foreground',
                disabled && 'opacity-60',
                className
            )}
        >
            <Popover open={open} onOpenChange={setOpen}>
                <PopoverTrigger asChild>
                    <button
                        type="button"
                        disabled={disabled}
                        aria-label={
                            country
                                ? `Country: ${regionNames?.of(country) ?? country}`
                                : 'Choose a country'
                        }
                        className="flex h-full shrink-0 items-center gap-2 rounded-l-xl pl-4 pr-3 outline-none transition-colors hover:bg-foreground/[0.04] focus-visible:bg-foreground/[0.06]"
                    >
                        <Flag country={country} />
                        <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                    </button>
                </PopoverTrigger>
                <PopoverContent
                    align="start"
                    sideOffset={6}
                    // Above the auth modal (z-[100]) this picker can sit inside.
                    className="z-[120] w-72 overflow-hidden p-0"
                    onOpenAutoFocus={(e) => e.preventDefault()}
                >
                    <div className="flex items-center gap-2 border-b border-border px-3">
                        <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        <input
                            // eslint-disable-next-line jsx-a11y/no-autofocus -- the picker opens to search
                            autoFocus
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' && matches[0]) {
                                    e.preventDefault();
                                    pick(matches[0].code);
                                }
                            }}
                            placeholder="Search countries"
                            className="h-10 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                        />
                    </div>
                    <div
                        className="max-h-72 overflow-y-auto py-1"
                        role="listbox"
                    >
                        {matches.map((c) => (
                            <button
                                key={c.code}
                                type="button"
                                role="option"
                                aria-selected={c.code === country}
                                onClick={() => pick(c.code)}
                                className="flex w-full items-center gap-3 px-3 py-2 text-left text-sm transition-colors hover:bg-accent"
                            >
                                <Flag country={c.code} />
                                <span className="flex-1 truncate">
                                    {c.name}
                                </span>
                                <span className="text-muted-foreground">
                                    +{c.callingCode}
                                </span>
                                <Check
                                    className={cn(
                                        'h-3.5 w-3.5',
                                        c.code === country
                                            ? 'opacity-100'
                                            : 'opacity-0'
                                    )}
                                />
                            </button>
                        ))}
                        {matches.length === 0 && (
                            <p className="px-3 py-6 text-center text-sm text-muted-foreground">
                                No country matches
                            </p>
                        )}
                    </div>
                </PopoverContent>
            </Popover>
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
