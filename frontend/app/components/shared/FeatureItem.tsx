// Standardized benefit/strength row for the marketing pages. Replaces the old
// per-page colored dot bullets (violet on /mcp, per-harness accent on /agents)
// with one neutral checkmark in a soft circle, on the marketing pages' wash, so the
// "why / about" feature lists look consistent everywhere.
import type { ReactNode } from 'react';
import { Check } from 'lucide-react';

export function FeatureItem({ children }: { children: ReactNode }) {
    return (
        <div className="flex items-start gap-3 rounded-2xl bg-card px-5 py-4 ring-1 ring-inset ring-foreground/[0.07] dark:bg-foreground/[0.04] dark:ring-0">
            <span className="mt-0.5 flex h-[18px] w-[18px] flex-shrink-0 items-center justify-center rounded-full bg-foreground/[0.1]">
                <Check className="h-3 w-3 text-foreground/75" strokeWidth={2.5} />
            </span>
            <span className="text-[15px] leading-relaxed text-foreground/75">{children}</span>
        </div>
    );
}
