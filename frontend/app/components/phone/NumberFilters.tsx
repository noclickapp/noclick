// What a number search narrows by: the country (opening on the person's own), the kind of number sold there, a city,
// region or area code (suggested from where numbers are for sale), digits it contains, and whether it must take texts
// too. A pick searches at once; typed text searches on Enter or Search.
import { useId, useMemo, useState, type FormEvent } from 'react';
import { ChevronDown, Loader2, MapPin, Search } from 'lucide-react';
import { CountryFlag, CountryPicker, countryName } from '~/components/ui/country-picker';
import { coverageDetail, TYPE_LABELS, type PhoneNumberPurchase, type PlaceKind } from '~/hooks/usePhoneNumberPurchase';
import { cn } from '~/lib/utils';
import { BUTTON_PRIMARY } from '~/components/shell/buttons';

const INPUT =
    'h-10 w-full rounded-full border border-border bg-transparent px-4 text-[14px] text-foreground outline-none transition-colors placeholder:text-[hsl(var(--placeholder))] focus:border-foreground/25 disabled:opacity-60 dark:border-foreground/[0.1]';
const PILL = 'inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-3 text-[13px] transition-colors disabled:opacity-60';
const PILL_ON = 'bg-primary text-primary-foreground';
const PILL_OFF = 'bg-secondary text-foreground/85 hover:bg-accent dark:bg-foreground/[0.06] dark:hover:bg-foreground/[0.1]';
const MAX_SUGGESTIONS = 8;

interface Suggestion {
    kind: PlaceKind;
    value: string;
    detail: string;
}

/** The places a typed fragment matches: cities or area codes, then whole regions. */
function suggestionsFor(text: string, places: PhoneNumberPurchase['places']): Suggestion[] {
    const q = text.trim().toLowerCase();
    if (!q) return [];
    const regions = [...new Set(places.map((p) => p.region).filter(Boolean))];
    const found: Suggestion[] = [
        ...places
            .filter((p) => p.value.toLowerCase().startsWith(q) || (p.kind === 'locality' && p.value.toLowerCase().includes(q)))
            .map((p) => ({ kind: p.kind, value: p.value, detail: [p.kind === 'area_code' ? 'Area code' : '', p.region].filter(Boolean).join(' · ') })),
        ...regions.filter((r) => r.toLowerCase().startsWith(q)).map((r) => ({ kind: 'region' as const, value: r, detail: 'Region' })),
    ];
    return found.slice(0, MAX_SUGGESTIONS);
}

export function NumberFilters({ purchase, compact = false }: { purchase: PhoneNumberPurchase; compact?: boolean }) {
    const { filters, coverage, country, places, busy, searching, update } = purchase;
    const [placeOpen, setPlaceOpen] = useState(false);
    const listId = useId();
    const suggestions = useMemo(() => suggestionsFor(filters?.place ?? '', places), [filters?.place, places]);
    const countries = useMemo(() => (coverage ?? []).map((c) => ({ code: c.country, detail: coverageDetail(c) })), [coverage]);
    if (!filters) return null;

    const onSubmit = (e: FormEvent) => {
        e.preventDefault();
        setPlaceOpen(false);
        update({}, true);
    };
    const placeHolder = filters.country === 'US' || filters.country === 'CA' ? 'City, state or area code' : 'City or region';

    return (
        <form onSubmit={onSubmit} className={cn('flex flex-col', compact ? 'gap-2.5' : 'gap-3')} aria-label="Find a number">
            <div className="flex flex-wrap items-center gap-2">
                <CountryPicker
                    value={filters.country}
                    options={countries}
                    disabled={busy || !coverage}
                    onPick={(code) => update({ country: code })}
                    trigger={
                        <button
                            type="button"
                            aria-label={`Country: ${countryName(filters.country)}`}
                            className={cn(PILL, PILL_OFF, 'h-9 gap-2 pl-2.5 pr-3 text-[13.5px]')}
                        >
                            <CountryFlag country={filters.country} className="h-3.5 w-5" />
                            <span className="max-w-[12rem] truncate">{countryName(filters.country)}</span>
                            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                        </button>
                    }
                />
                {country && country.number_types.length > 1 && (
                    <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Kind of number">
                        {country.number_types.map((type) => (
                            <button
                                key={type}
                                type="button"
                                role="radio"
                                aria-checked={filters.numberType === type}
                                disabled={busy}
                                onClick={() => update({ numberType: type })}
                                className={cn(PILL, filters.numberType === type ? PILL_ON : PILL_OFF)}
                            >
                                {TYPE_LABELS[type]}
                            </button>
                        ))}
                    </div>
                )}
            </div>
            {country && (
                <div className="flex flex-wrap items-center gap-2">
                    <div className="relative min-w-[12rem] flex-[2_1_14rem]">
                        <MapPin className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                        <input
                            value={filters.place}
                            onChange={(e) => {
                                update({ place: e.target.value.slice(0, 64), placeKind: null }, false);
                                setPlaceOpen(true);
                            }}
                            onFocus={() => setPlaceOpen(true)}
                            onBlur={() => setPlaceOpen(false)}
                            placeholder={placeHolder}
                            aria-label="City, region or area code"
                            role="combobox"
                            aria-expanded={placeOpen && suggestions.length > 0}
                            aria-autocomplete="list"
                            aria-controls={listId}
                            className={cn(INPUT, 'pl-10')}
                        />
                        {placeOpen && suggestions.length > 0 && (
                            <div id={listId} role="listbox" className="absolute left-0 right-0 top-full z-20 mt-1.5 overflow-hidden rounded-2xl border border-border bg-popover py-1 shadow-lg">
                                {suggestions.map((s) => (
                                    <button
                                        key={`${s.kind}:${s.value}`}
                                        type="button"
                                        role="option"
                                        aria-selected={false}
                                        // Before the input's blur closes the list.
                                        onMouseDown={(e) => {
                                            e.preventDefault();
                                            setPlaceOpen(false);
                                            update({ place: s.value, placeKind: s.kind });
                                        }}
                                        className="flex w-full items-baseline justify-between gap-3 px-3.5 py-2 text-left text-[13.5px] transition-colors hover:bg-accent"
                                    >
                                        <span className="truncate">{s.value}</span>
                                        <span className="shrink-0 text-[12px] text-muted-foreground">{s.detail}</span>
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>
                    <input
                        value={filters.contains}
                        onChange={(e) => update({ contains: e.target.value.toUpperCase().replace(/[^0-9A-Z*]/g, '').slice(0, 10) }, false)}
                        placeholder="Digits it contains"
                        aria-label="Digits or letters the number contains"
                        className={cn(INPUT, 'min-w-[9rem] flex-[1_1_9rem] tabular-nums')}
                    />
                    <div className="flex gap-1.5" role="radiogroup" aria-label="What the number must do">
                        {(
                            [
                                ['voice', 'Calls'],
                                ['voice_sms', 'Calls and texts'],
                            ] as const
                        ).map(([value, label]) => (
                            <button
                                key={value}
                                type="button"
                                role="radio"
                                aria-checked={filters.features === value}
                                disabled={busy}
                                onClick={() => update({ features: value })}
                                className={cn(PILL, 'h-10', filters.features === value ? PILL_ON : PILL_OFF)}
                            >
                                {label}
                            </button>
                        ))}
                    </div>
                    <button type="submit" disabled={busy} className={cn(BUTTON_PRIMARY, 'h-10 px-5')}>
                        {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                        Search
                    </button>
                </div>
            )}
        </form>
    );
}
