// What NoClick keeps or hands you: what it will remember (with the way to take it back), and a way to carry this
// thread to your phone.
import type { ReactNode } from 'react';
import { ArrowUpRight, Brain } from 'lucide-react';
import { QrCode } from '~/components/shared/QrCode';
import { ChannelTile } from '~/components/shell/AppTile';
import { cn } from '~/lib/utils';
import type { PhoneApp } from './channels';
import { CARD, PILL_SECONDARY, Receipt } from './primitives';

/** NoClick noting something for next time: what, and the way to take it back. */
export function MemoryLine({ fact, forgotten = false, action }: { fact: string; forgotten?: boolean; action?: ReactNode }) {
    return (
        <Receipt tone="info" lead={<Brain className="h-4 w-4 shrink-0 text-foreground/60" />} action={action}>
            {forgotten ? `Won’t remember: ${fact}` : `Remembered: ${fact}`}
        </Receipt>
    );
}

const APP_NAMES: Record<PhoneApp, { name: string; open: string }> = {
    whatsapp: { name: 'WhatsApp', open: 'Open WhatsApp' },
    imessage: { name: 'iMessage', open: 'Open Messages' },
};

/** Carry the thread to a phone: the code links the phone it's sent from to this account. The QR leads, and what it
 *  does sits beside it, so nothing waits under a header; a narrow card stacks them. `href` is null while a fresh code
 *  is minted, and the code is drawn as a placeholder until it lands. */
export function PhoneHandoffCard({ app, number, href, placeholder }: { app: PhoneApp; number: string; href: string | null; placeholder?: ReactNode }) {
    const { name, open } = APP_NAMES[app];
    return (
        <section className={cn(CARD, '@container p-4')} data-testid="coordinator-phone-handoff">
            <div className="flex flex-col gap-4 @[420px]:flex-row">
                {href ? <QrCode value={href} label={`Scan to text NoClick on ${name}`} mark={<ChannelTile channel={app} size="sm" />} className="w-[132px] shrink-0" /> : placeholder}
                {/* Title level with the code's top, the way out level with its foot. */}
                <div className="flex min-w-0 flex-1 flex-col">
                    <h3 className="flex items-center gap-2 text-[14.5px] font-medium leading-5 tracking-[-0.005em] text-foreground">
                        <ChannelTile channel={app} size="sm" />
                        Keep going on {name}
                    </h3>
                    <p className="mt-1 text-[13.5px] leading-snug text-muted-foreground">Scan with your phone and send the message it starts. Everything here carries over.</p>
                    <div className="mt-auto flex items-center justify-between gap-3 pt-3">
                        <span className="font-mono text-[14px] tabular-nums text-foreground">{number}</span>
                        <a
                            href={href ?? undefined}
                            target="_blank"
                            rel="noopener noreferrer"
                            aria-disabled={!href}
                            className={cn(PILL_SECONDARY, !href && 'pointer-events-none opacity-50')}
                        >
                            {open}
                            <ArrowUpRight className="h-3.5 w-3.5" />
                        </a>
                    </div>
                </div>
            </div>
        </section>
    );
}
