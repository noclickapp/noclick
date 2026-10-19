// The sidebar's nudge to text NoClick from a phone, shown until one is linked: the texting app most people where you
// are use first (preferredTextApp) with a switch to the other, and a code to scan whose drafted message links the phone
// that sends it (on a phone, the app itself, opened on that message). Its × puts it away until the page is reloaded.
import { useState } from 'react';
import { ArrowUpRight, X } from 'lucide-react';
import { HAIRLINE } from '~/components/dashboard/primitives';
import { QrCode, QrPlaceholder } from '~/components/shared/QrCode';
import { Button } from '~/components/ui/button';
import { useIsMobile } from '~/hooks/useIsMobile';
import { TEXT_APP_ORDER, useTextNoClick } from '~/hooks/useTextNoClick';
import { formatPhoneForDisplay } from '~/lib/phoneFormat';
import { cn } from '~/lib/utils';
import { ChannelTile } from './AppTile';
import { TEXT_APPS, type TextApp } from './textApp';

// Dismissed for this page's life, so collapsing the sidebar or reopening the phone menu doesn't bring it back.
let dismissedThisLoad = false;
// The card's width at the default sidebar; a wider sidebar centres it rather than growing it.
const QR_SIZE = 'mx-auto mt-2.5 w-full max-w-[220px] rounded-xl';

function AppSwitch({ value, onChange }: { value: TextApp; onChange: (app: TextApp) => void }) {
    // The chosen app in colour inside a hairline of its own shape; the other greyed until pointed at.
    return (
        <div role="radiogroup" aria-label="Texting app" className="flex shrink-0 items-center gap-2.5 pl-1">
            {TEXT_APP_ORDER.map((app) => (
                <button
                    key={app}
                    type="button"
                    role="radio"
                    aria-checked={value === app}
                    aria-label={TEXT_APPS[app].label}
                    title={TEXT_APPS[app].label}
                    onClick={() => onChange(app)}
                    className={cn(
                        'rounded-[7px] transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card',
                        value === app ? 'outline outline-[1.5px] outline-offset-2 outline-foreground/30' : 'opacity-45 grayscale hover:opacity-90 hover:grayscale-0'
                    )}
                >
                    <ChannelTile channel={app} size="sm" className="h-6 w-6 rounded-[7px]" />
                </button>
            ))}
        </div>
    );
}

export function TextNoClickBanner() {
    const [dismissed, setDismissed] = useState(() => dismissedThisLoad);
    const dismiss = () => {
        dismissedThisLoad = true;
        setDismissed(true);
    };
    const { ready, app, number, href, offered, pick } = useTextNoClick(!dismissed, { announceLink: true });
    const isMobile = useIsMobile();
    if (!ready) return null;
    const { label, app: appName } = TEXT_APPS[app];
    const switcher = offered.length > 1 && <AppSwitch value={app} onChange={pick} />;

    return (
        <section
            aria-label="Text NoClick from your phone"
            data-testid="text-noclick-banner"
            className={cn(
                'relative mb-1.5 rounded-2xl border bg-background/60 p-2.5 dark:bg-foreground/[0.03] motion-safe:duration-300 motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1',
                HAIRLINE
            )}
        >
            <button
                type="button"
                aria-label="Dismiss"
                onClick={dismiss}
                className="absolute right-1.5 top-1.5 grid h-6 w-6 place-items-center rounded-full text-muted-foreground/70 transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
                <X className="h-3.5 w-3.5" strokeWidth={2} />
            </button>
            <div className="flex items-center gap-2.5 pr-6">
                <ChannelTile channel={app} />
                <div className="min-w-0">
                    <p className="truncate text-[13.5px] font-medium leading-5 tracking-[-0.005em] text-foreground">Text NoClick</p>
                    <p className="truncate text-[12.5px] leading-4 text-muted-foreground" data-testid="text-noclick-banner-app">
                        on {label}
                    </p>
                </div>
            </div>
            {isMobile ? (
                // A phone is what does the texting: the app itself, opened on the message that links it.
                <>
                    <p className="mt-2.5 text-[12.5px] leading-[1.45] text-muted-foreground">Reach this same conversation from your phone, like any contact.</p>
                    <div className="mt-3 flex items-center gap-2">
                        {href ? (
                            <Button asChild size="sm" className="h-8 min-w-0 flex-1 rounded-full px-3 text-[13px]">
                                <a href={href} target="_blank" rel="noopener noreferrer" data-testid="text-noclick-banner-open">
                                    Open {appName}
                                </a>
                            </Button>
                        ) : (
                            <Button size="sm" className="h-8 min-w-0 flex-1 rounded-full px-3 text-[13px]" disabled>
                                Open {appName}
                            </Button>
                        )}
                        {switcher}
                    </div>
                </>
            ) : (
                <>
                    {/* Never a code near its end: the slot waits for the next one instead. */}
                    {href ? (
                        <QrCode
                            value={href}
                            label={`Scan to message NoClick on ${label} at ${formatPhoneForDisplay(number)}`}
                            mark={<ChannelTile channel={app} />}
                            className={QR_SIZE}
                        />
                    ) : (
                        <QrPlaceholder label="Getting a fresh code" className={QR_SIZE} />
                    )}
                    <div className="mt-2.5 flex items-center justify-between gap-2">
                        {switcher}
                        {href && (
                            <a
                                href={href}
                                target="_blank"
                                rel="noopener noreferrer"
                                data-testid="text-noclick-banner-open"
                                className="ml-auto inline-flex items-center gap-0.5 rounded-md text-[12.5px] text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            >
                                Open {appName}
                                <ArrowUpRight className="h-3.5 w-3.5" />
                            </a>
                        )}
                    </div>
                </>
            )}
        </section>
    );
}
