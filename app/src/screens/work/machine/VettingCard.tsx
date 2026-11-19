// The company NoClick checks once before an account's first machine, as a card in the rent confirm: its name, website,
// where it's registered and what its agents do, each changed in place with Edit (an empty one asks for itself). It's
// sent with the rental, which starts the moment NoClick approves it.
import { useEffect, useRef, useState } from 'react';
import { cn } from '@/ui/utils';

export interface VettingDraft {
    company_name: string;
    website: string;
    /** ISO 3166-1 alpha-2, as the API takes it. */
    country: string;
    use_case: string;
}

const FIELDS: [keyof VettingDraft, string, string][] = [
    ['company_name', 'Company', 'Its legal name'],
    ['website', 'Website', 'example.com'],
    ['country', 'Registered in', 'Country code, like GB'],
    ['use_case', 'What agents do', 'What its machines and agents will do'],
];

const COUNTRY = /^[A-Za-z]{2}$/;

/** Every field filled, and a country as its two-letter code. */
export const vettingReady = (d: VettingDraft) =>
    !!d.company_name.trim() &&
    !!d.website.trim() &&
    COUNTRY.test(d.country.trim()) &&
    !!d.use_case.trim();

function countryName(code: string): string {
    const c = code.trim().toUpperCase();
    if (!COUNTRY.test(c)) return code;
    try {
        return new Intl.DisplayNames(['en'], { type: 'region' }).of(c) ?? c;
    } catch {
        return c;
    }
}

export function VettingCard({
    value,
    onChange,
    editable,
}: {
    value: VettingDraft;
    onChange: (next: VettingDraft) => void;
    editable: boolean;
}) {
    const [editing, setEditing] = useState<keyof VettingDraft | null>(null);
    const fields = useRef<
        Partial<Record<keyof VettingDraft, HTMLInputElement | null>>
    >({});
    // Edit puts the cursor in the field it opens.
    useEffect(() => {
        if (editing) fields.current[editing]?.focus();
    }, [editing]);
    return (
        <div
            className="overflow-hidden rounded-2xl ring-1 ring-inset ring-border dark:ring-foreground/[0.1]"
            data-testid="vetting-card"
        >
            {FIELDS.map(([key, label, hint]) => {
                const v = value[key];
                const asking = editable && (editing === key || !v.trim());
                return (
                    <div
                        key={key}
                        className="flex items-center gap-3 border-b border-border px-3 py-2 last:border-0 dark:border-foreground/[0.06]"
                    >
                        <span className="w-[88px] shrink-0 text-[12.5px] text-muted-foreground">
                            {label}
                        </span>
                        {asking ? (
                            <input
                                aria-label={label}
                                value={v}
                                placeholder={hint}
                                ref={(el) => {
                                    fields.current[key] = el;
                                }}
                                maxLength={
                                    key === 'use_case'
                                        ? 2000
                                        : key === 'country'
                                          ? 2
                                          : 300
                                }
                                onChange={(e) =>
                                    onChange({
                                        ...value,
                                        [key]:
                                            key === 'country'
                                                ? e.target.value.toUpperCase()
                                                : e.target.value,
                                    })
                                }
                                onFocus={() => setEditing(key)}
                                onBlur={() => setEditing(null)}
                                onKeyDown={(e) =>
                                    e.key === 'Enter' && setEditing(null)
                                }
                                className={cn(
                                    'h-8 min-w-0 flex-1 rounded-full bg-foreground/[0.05] px-3 text-[13px] outline-none placeholder:text-muted-foreground/70 focus-visible:ring-2 focus-visible:ring-ring'
                                )}
                            />
                        ) : (
                            <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
                                {key === 'country' ? countryName(v) : v}
                            </span>
                        )}
                        {editable && !asking && (
                            <button
                                type="button"
                                onClick={() => setEditing(key)}
                                className="h-7 shrink-0 rounded-full px-2.5 text-[12px] font-medium text-muted-foreground ring-1 ring-inset ring-border transition-colors hover:text-foreground dark:ring-foreground/[0.12]"
                            >
                                Edit
                            </button>
                        )}
                    </div>
                );
            })}
        </div>
    );
}
