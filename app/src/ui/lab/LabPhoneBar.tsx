// What a page lab draws a phone-wide window in: the phone shell's top bar as the page's views see it (the page's
// name, or a view's way back in its place, and the view's actions at its end). The shell's menu, which opens the
// app's pages, isn't drawn.
import { useState, type ReactNode } from 'react';
import { PhoneBarSlotProvider } from '@/ui/phoneBar';

export function LabPhoneBar({ title, children }: { title: string; children: ReactNode }) {
    const [slot, setSlot] = useState<HTMLElement | null>(null);
    const [lead, setLead] = useState<HTMLElement | null>(null);
    const [taken, setTaken] = useState(false);
    return (
        <>
            <header className="flex h-12 shrink-0 items-center gap-1 px-2">
                <span className={taken ? 'hidden' : 'min-w-0 flex-1 truncate px-1 text-[15px] font-semibold tracking-[-0.01em] text-foreground'}>{title}</span>
                <div ref={setLead} className={taken ? 'flex min-w-0 flex-1 items-center gap-1' : 'hidden'} />
                <div ref={setSlot} className="flex min-w-0 items-center gap-0.5" />
            </header>
            <PhoneBarSlotProvider slot={slot} lead={lead} setLeadTaken={setTaken}>
                {children}
            </PhoneBarSlotProvider>
        </>
    );
}
