// One number for sale: the number as its country writes it (the digits a search asked for marked), where it rings,
// what it can do, its price a month and once, and what its country asks before it's sold (said in full once, above the
// list: NumberFinder). The surface supplies the action beside it and what opens under it.
import type { ReactNode } from 'react';
import { Phone } from 'lucide-react';
import type { AvailableNumber } from '~/hooks/usePhoneNumberPurchase';
import { patternSpan } from '~/lib/phoneFormat';
import { cn } from '~/lib/utils';
import { asksContactPhone, capabilityLabels, formatNumber, placeOf, priceText } from './numberDisplay';

export function NumberLabel({ e164, pattern }: { e164: string; pattern: string }) {
    const shown = formatNumber(e164);
    const span = patternSpan(e164, pattern);
    if (!span) return <span className="font-medium tabular-nums text-foreground">{shown}</span>;
    // Map digit positions back onto the grouped display (spaces and the + are skipped).
    const parts: { text: string; hit: boolean }[] = [];
    let digitIndex = 0;
    for (const ch of shown) {
        const isDigit = /\d/.test(ch);
        const hit = isDigit && digitIndex >= span[0] && digitIndex < span[1];
        if (isDigit) digitIndex += 1;
        const last = parts[parts.length - 1];
        if (last && last.hit === hit) last.text += ch;
        else parts.push({ text: ch, hit });
    }
    return (
        <span className="font-medium tabular-nums text-foreground">
            {parts.map((p, i) => (p.hit ? <mark key={i} className="rounded-sm bg-primary/20 px-0.5 text-foreground">{p.text}</mark> : <span key={i}>{p.text}</span>))}
        </span>
    );
}

export function NumberPrice({ number, className }: { number: Pick<AvailableNumber, 'monthly_credits' | 'upfront_credits'>; className?: string }) {
    const price = priceText(number);
    return (
        <div className={cn('text-right leading-tight', className)}>
            <p className="text-[14px] tabular-nums text-foreground">
                {price.monthly}
                <span className="text-[12.5px] text-muted-foreground">/mo</span>
            </p>
            {price.upfront && <p className="mt-0.5 text-[12px] tabular-nums text-muted-foreground">+ {price.upfront} once</p>}
        </div>
    );
}

export function NumberRow({
    number,
    pattern,
    action,
    children,
    highlighted,
    compact = false,
}: {
    number: AvailableNumber;
    pattern: string;
    /** The button beside it (Buy, Review). */
    action: ReactNode;
    /** What opens under it (a confirmation). */
    children?: ReactNode;
    highlighted?: boolean;
    compact?: boolean;
}) {
    const needs = number.requirements.needs;
    return (
        <div className={cn('transition-colors', compact ? 'px-3 py-2.5' : 'px-4 py-3.5 sm:px-5', highlighted && 'bg-foreground/[0.03]')} data-testid="available-number">
            <div className="flex flex-wrap items-center gap-x-3.5 gap-y-2">
                {!compact && (
                    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-foreground/[0.05]">
                        <Phone className="h-[18px] w-[18px] text-foreground/75" strokeWidth={1.75} />
                    </span>
                )}
                <div className="min-w-0 flex-[1_1_12rem]">
                    <p className={cn('truncate', compact ? 'text-[13.5px]' : 'text-[15px]')}>
                        <NumberLabel e164={number.phone_number} pattern={pattern} />
                    </p>
                    <p className="mt-0.5 truncate text-[12.5px] text-muted-foreground">{[placeOf(number), ...capabilityLabels(number.capabilities)].join(' · ')}</p>
                    {needs === 'address' && (
                        <p className="mt-1 text-[12.5px] text-muted-foreground">
                            Needs the holder’s {asksContactPhone(number) ? 'name, address and phone' : 'name and address'}, asked when you buy it.
                        </p>
                    )}
                    {needs === 'documents' && <p className="mt-1 text-[12.5px] text-muted-foreground">Needs documents, added when you buy it; the carrier reviews them first.</p>}
                </div>
                <div className="ml-auto flex shrink-0 items-center gap-3">
                    <NumberPrice number={number} />
                    {action}
                </div>
            </div>
            {children}
        </div>
    );
}
