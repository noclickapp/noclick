// A popup's way back to the page it slid from ("‹ Sizes", "‹ Add your computer"), a quiet pill at the body's top: the
// machine-buying popup and Add your computer's settings page both slide this way.
import { ChevronLeft } from 'lucide-react';

export function BackLink({ label, onClick }: { label: string; onClick: () => void }) {
    return (
        <button type="button" onClick={onClick} className="-ml-2 mb-2 inline-flex h-[30px] items-center gap-1 rounded-full pl-1.5 pr-2.5 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <ChevronLeft className="h-4 w-4" strokeWidth={2} />
            {label}
        </button>
    );
}

/** A popup page sliding in: forward from the right, back from the left (still where motion is reduced). */
export const slideIn = (back: boolean) => `duration-200 animate-in fade-in-0 motion-reduce:animate-none ${back ? 'slide-in-from-left-4' : 'slide-in-from-right-4'}`;
