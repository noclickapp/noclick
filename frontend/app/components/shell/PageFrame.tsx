// The frame every shell page shares: a scrolling column with the page's title
// and one line on what lives here. On a phone the top bar carries the title.
// A page one level down names the page it came from: a breadcrumb on a laptop,
// the bar's back button on a phone.
import type { ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';
import { PhoneBarBack, useInPhoneShell } from './AppShell';
import { PAGE_TITLE } from './titles';

export function PageFrame({
    title,
    description,
    actions,
    back,
    children,
}: {
    title: string;
    /** The page's own buttons, beside the title (under the description on a phone). */
    actions?: ReactNode;
    description?: ReactNode;
    back?: { label: string; onBack: () => void };
    children: ReactNode;
}) {
    const inPhone = useInPhoneShell();
    return (
        <div className="h-full overflow-y-auto scrollbar-subtle">
            <div className="mx-auto w-full max-w-[1080px] px-5 pb-24 pt-5 sm:px-8 sm:pt-10">
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
                {(!inPhone || description || actions) && (
                    <header className="mb-7 flex min-w-0 flex-wrap items-start gap-x-6 gap-y-4">
                        <div className="min-w-0 flex-1">
                            {!inPhone && <h1 className={PAGE_TITLE}>{title}</h1>}
                            {description ? <p className="mt-1 text-[14px] text-muted-foreground">{description}</p> : null}
                        </div>
                        {actions && <div className="flex shrink-0 items-center gap-2 sm:pt-1">{actions}</div>}
                    </header>
                )}
                {children}
            </div>
        </div>
    );
}
