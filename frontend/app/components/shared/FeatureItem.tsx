// Standardized benefit/strength row for the marketing pages. Replaces the old
// per-page colored dot bullets (violet on /mcp, per-harness accent on /agents)
// with one neutral, Apple-style checkmark in a subtle circle so the "why / about"
// feature lists look consistent everywhere. Used by /mcp and the /agents pages.
import type { ReactNode } from 'react';
import { Check } from 'lucide-react';
import { CARD } from '~/lib/cardStyles';

export function FeatureItem({ children }: { children: ReactNode }) {
    return (
        <div className={`flex items-start gap-3 rounded-lg ${CARD} px-4 py-3`}>
            <span className="mt-px flex h-[18px] w-[18px] flex-shrink-0 items-center justify-center rounded-full border border-foreground/10 bg-foreground/[0.08]">
                <Check className="h-3 w-3 text-foreground/70" strokeWidth={2.5} />
            </span>
            <span className="text-sm text-foreground/60 leading-relaxed">{children}</span>
        </div>
    );
}
