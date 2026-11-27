// The frame every shell page shares: a scrolling column with the page's title
// and one line on what lives here. On a phone the top bar carries the title.
// A page one level down names the page it came from: a breadcrumb on a laptop,
// the bar's back button on a phone.
import { createContext, useContext, type ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';
import { PhoneBarBack, useInPhoneShell } from '@/ui/phoneBar';
import { PageHead } from '@/ui/PageHead';
import { cn } from '@/ui/utils';

/** True where a page is drawn inside another frame that scrolls and pads it already (the developer console's): the
 *  page keeps its head and body, and lays out where that frame puts it. */
export const InHostFrame = createContext(false);

export function PageFrame({
    title,
    description,
    actions,
    back,
    children,
}: {
    title: string;
    /** The page's own buttons, beside the title (under the description where the page is narrow). */
    actions?: ReactNode;
    description?: ReactNode;
    back?: { label: string; onBack: () => void };
    children: ReactNode;
}) {
    const inPhone = useInPhoneShell();
    const hosted = useContext(InHostFrame);
    return (
        // Relative: what a page positions (a screen-reader live region) lays out in its scroll, not the shell's.
        <div className={cn('relative', !hosted && 'h-full overflow-y-auto scrollbar-subtle')}>
            <div className={hosted ? 'w-full' : 'mx-auto w-full max-w-[1080px] px-5 pb-24 pt-5 sm:px-8 sm:pt-10'}>
                {back &&
                    (inPhone ? (
                        <PhoneBarBack label={back.label} title={title} onBack={back.onBack} />
                    ) : (
                        <nav aria-label="Breadcrumb" className="-mt-4 mb-3 flex items-center gap-1 text-[13px] text-muted-foreground">
                            <button type="button" onClick={back.onBack} className="-ml-1 rounded-md px-1 py-0.5 transition-colors hover:text-foreground">
                                {back.label}
                            </button>
                            <ChevronRight className="h-3.5 w-3.5 opacity-60" />
                        </nav>
                    ))}
                {(!inPhone || hosted || description || actions) && <PageHead className="mb-7" title={inPhone && !hosted ? undefined : title} line={description} actions={actions} />}
                {children}
            </div>
        </div>
    );
}
