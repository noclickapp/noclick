// A country: its flag, its name in English, and a searchable picker over a
// list of them. The phone input picks a calling code with it; buying a number
// picks the country to buy in.
import { useMemo, useState, type ReactNode } from 'react';
import type { CountryCode } from 'libphonenumber-js';
import * as Flags from 'country-flag-icons/react/3x2';
import { Check, Globe, Search } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '~/components/ui/popover';
import { cn } from '~/lib/utils';

const regionNames = typeof Intl !== 'undefined' && 'DisplayNames' in Intl ? new Intl.DisplayNames(['en'], { type: 'region' }) : null;

export function countryName(code: string): string {
    return regionNames?.of(code) ?? code;
}

export function CountryFlag({ country, className }: { country?: string; className?: string }) {
    const Icon = country ? (Flags as Record<string, typeof Flags.US>)[country] : undefined;
    if (!Icon) return <Globe className={cn('h-4 w-5 text-muted-foreground', className)} />;
    return <Icon title="" className={cn('h-4 w-6 rounded-[2px] object-cover', className)} />;
}

export interface CountryOption {
    code: CountryCode | string;
    /** What the list shows with the name: a calling code, the kinds of number sold there. */
    detail?: string;
    /** More words the search matches (a calling code). */
    keywords?: string[];
}

export function CountryPicker({
    value,
    options,
    onPick,
    trigger,
    disabled,
    zIndexClassName,
    detailBeside = false,
}: {
    value?: string;
    options: CountryOption[];
    onPick: (code: string) => void;
    /** The button that opens the picker. */
    trigger: ReactNode;
    disabled?: boolean;
    /** Above a modal the picker sits inside. */
    zIndexClassName?: string;
    /** A short detail (a calling code) on the name's line; otherwise it's a line of its own under the name. */
    detailBeside?: boolean;
}) {
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState('');
    const named = useMemo(() => options.map((o) => ({ ...o, name: countryName(o.code) })).sort((a, b) => a.name.localeCompare(b.name)), [options]);
    const matches = useMemo(() => {
        const q = query.trim().toLowerCase().replace(/^\+/, '');
        if (!q) {
            // The current country first, so the list opens on it.
            const current = named.find((c) => c.code === value);
            return current ? [current, ...named.filter((c) => c !== current)] : named;
        }
        return named.filter((c) => c.name.toLowerCase().includes(q) || c.code.toLowerCase() === q || (c.keywords ?? []).some((k) => k.startsWith(q)));
    }, [query, named, value]);
    const pick = (code: string) => {
        setOpen(false);
        setQuery('');
        onPick(code);
    };
    return (
        <Popover open={open} onOpenChange={disabled ? undefined : setOpen}>
            <PopoverTrigger asChild disabled={disabled}>
                {trigger}
            </PopoverTrigger>
            <PopoverContent align="start" sideOffset={6} className={cn('w-72 overflow-hidden p-0', zIndexClassName)} onOpenAutoFocus={(e) => e.preventDefault()}>
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
                        aria-label="Search countries"
                        className="h-10 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                    />
                </div>
                <div className="scrollbar-subtle max-h-72 overflow-y-auto overflow-x-hidden py-1" role="listbox">
                    {matches.map((c) => (
                        <button
                            key={c.code}
                            type="button"
                            role="option"
                            aria-selected={c.code === value}
                            onClick={() => pick(c.code)}
                            className="flex w-full items-center gap-3 px-3 py-2 text-left text-sm transition-colors hover:bg-accent"
                        >
                            <CountryFlag country={c.code} className="shrink-0" />
                            {detailBeside ? (
                                <>
                                    <span className="min-w-0 flex-1 truncate">{c.name}</span>
                                    {c.detail && <span className="shrink-0 text-[12.5px] tabular-nums text-muted-foreground">{c.detail}</span>}
                                </>
                            ) : (
                                <span className="min-w-0 flex-1">
                                    <span className="block truncate">{c.name}</span>
                                    {c.detail && (
                                        <span title={c.detail} className="block truncate text-[12px] leading-snug text-muted-foreground">
                                            {c.detail}
                                        </span>
                                    )}
                                </span>
                            )}
                            <Check className={cn('h-3.5 w-3.5 shrink-0', c.code === value ? 'opacity-100' : 'opacity-0')} />
                        </button>
                    ))}
                    {matches.length === 0 && <p className="px-3 py-6 text-center text-sm text-muted-foreground">No country matches</p>}
                </div>
            </PopoverContent>
        </Popover>
    );
}
