// "New …" for what's made in code: an agent, its triggers, a user, a webhook and most resources. The dialog shows the
// code that makes one, the prompt that has a coding agent write it, and the guide. Nothing here makes anything; it
// shows up in the console once the code runs. What each kind's dialog says is NEW_IN_CODE's, its code NEW_SNIPPETS'.
import { useState } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { cn } from '@/ui/utils';
import { HAIRLINE } from '@/ui/primitives';
import { useSlot } from '@/slots';
import { NEW_IN_CODE, guideLabel } from '@/screens/console/lib/newInCode';
import { NEW_SNIPPETS, snippetTabs, type NewKind, type NewPlace } from '@/screens/console/lib/snippets';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { invalidateV1 } from '@/sdk/useV1';
import { docsUrl } from '@/screens/console/lib/site';
import { CopyPromptAction, WorksWith, useCopyPrompt } from './Quickstart';
import { ConsoleButton, type ConsoleButtonProps } from './ui/Button';
import { CodeSnippet } from './ui/CodeSnippet';
import { ConsoleDialog } from './ui/ConsoleDialog';
import { useOwnerOnly } from './ownerOnly';
import { TERMS } from './slots';

const LABEL = 'm-0 mb-2.5 text-[13px] font-medium text-foreground/70 dark:text-muted-foreground';

/** Whether `kind`'s dialog is open: the address says `?new=<kind>`, so a link or the palette opens it. */
export function useNewParam(kind: NewKind): [boolean, (open: boolean) => void] {
    const [value, set] = useSearchParam('new');
    return [value === kind, (open) => set(open ? kind : null, open ? { push: true } : undefined)];
}

interface NewInCodeProps {
    kind: NewKind;
    /** Whose it is and where it goes; the code and the prompt both say so. */
    place?: NewPlace;
    /** In place of the kind's own title ("New channel in Ops"). */
    title?: string;
}

export function NewInCodeDialog({ kind, place = {}, title, open, onOpenChange }: NewInCodeProps & { open: boolean; onOpenChange: (open: boolean) => void }) {
    const entry = NEW_IN_CODE[kind];
    const copier = useCopyPrompt(entry, place);
    const { site } = useConsole();
    const Terms = useSlot(TERMS);
    const ownerCan = useOwnerOnly();
    const [lang, setLang] = useState('python');
    const Mark = entry.mark;
    // Closing it reads the page again, so what the code made while it was open shows at once.
    const close = (next: boolean) => {
        if (!next) invalidateV1('');
        onOpenChange(next);
    };
    return (
        <ConsoleDialog
            open={open}
            onOpenChange={close}
            size="lg"
            mark={<Mark aria-hidden className="h-5 w-5" />}
            title={title ?? entry.title}
            description={entry.description}
            footer={
                <>
                    <a href={docsUrl(site, entry.guide)} target="_blank" rel="noreferrer" className="mr-auto inline-flex items-center gap-1 text-[13px] text-muted-foreground transition-colors hover:text-foreground">
                        {guideLabel(entry.guide)} <ArrowUpRight aria-hidden className="h-3.5 w-3.5" />
                    </a>
                    <ConsoleButton onClick={() => close(false)}>Done</ConsoleButton>
                </>
            }
        >
            <div className="flex flex-col gap-6">
                <section aria-label="Create it from your code">
                    <h3 className={LABEL}>Create it from your code</h3>
                    <CodeSnippet tabs={snippetTabs(NEW_SNIPPETS[kind](place))} tab={lang} onTabChange={setLang} />
                </section>
                {ownerCan('setupCode') && (
                    <section aria-label="Or let your coding agent write it" className={cn('flex flex-col gap-3 border-t pt-6', HAIRLINE)}>
                        <div>
                            <h3 className={cn(LABEL, 'mb-1')}>Or let your coding agent write it</h3>
                            <p className="m-0 text-[13px] leading-relaxed text-muted-foreground">
                                One prompt: your coding agent installs NoClick, saves a key to your project without ever seeing it, and writes the code with you.
                            </p>
                        </div>
                        <WorksWith />
                        <CopyPromptAction copier={copier} />
                        <Terms action="copying the prompt" />
                    </section>
                )}
            </div>
        </ConsoleDialog>
    );
}

/** A kind's New button and the dialog it opens. */
export function NewInCode({ kind, place, title, label, variant = 'primary', ...button }: NewInCodeProps & { label?: string } & Omit<ConsoleButtonProps, 'onClick' | 'children'>) {
    const [open, setOpen] = useNewParam(kind);
    return (
        <>
            <ConsoleButton variant={variant} {...button} onClick={() => setOpen(true)}>
                {label ?? NEW_IN_CODE[kind].title}
            </ConsoleButton>
            <NewInCodeDialog kind={kind} place={place} title={title} open={open} onOpenChange={setOpen} />
        </>
    );
}
