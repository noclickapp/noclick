// Telling NoClick something from the account menu: a bug, an idea or anything else, sent with the SDK's `feedback`
// (`POST /v1/feedback`, which any of the account's keys may make, up to 20 notes a day). The menu's row (the
// `shell.account.items` standard) opens the dialog, which lives around the account row (`shell.account.around`), so
// it stays open once the menu has closed. It says what came of the note itself: the app shows no toasts.
import { APIConnectionError, feedback, NoClickError, type FeedbackKind } from 'noclick';
import { Bug, Lightbulb, MessageCircle, MessageSquarePlus } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { useClient } from '@/sdk/client';
import { ACCOUNT_MENU_ITEM } from '@/ui/accountParts';
import { BUTTON_GHOST, BUTTON_PRIMARY } from '@/ui/buttons';
import { DropdownMenuItem } from '@/ui/dropdown-menu';
import { ShellDialog } from '@/ui/ShellDialog';
import { Textarea } from '@/ui/textarea';
import { cn } from '@/ui/utils';

const OPEN_FEEDBACK = 'noclick:open-feedback';

/** Opens the feedback dialog from anywhere. */
export function openFeedback(): void {
    window.dispatchEvent(new Event(OPEN_FEEDBACK));
}

const KINDS: { kind: FeedbackKind; label: string; icon: typeof Bug }[] = [
    { kind: 'general', label: 'Feedback', icon: MessageCircle },
    { kind: 'bug', label: 'Bug', icon: Bug },
    { kind: 'idea', label: 'Idea', icon: Lightbulb },
];

/** The account menu's row that opens it. The dialog opens once the menu has closed, so the menu hands focus back
 *  before the dialog takes it. */
export function FeedbackMenuItem() {
    return (
        <DropdownMenuItem className={ACCOUNT_MENU_ITEM} onSelect={() => window.setTimeout(openFeedback)}>
            <MessageSquarePlus className="mr-2 h-4 w-4 text-muted-foreground" />
            <span>Send feedback</span>
        </DropdownMenuItem>
    );
}

/** Around the account row: the dialog, opened by `openFeedback`. */
export function FeedbackAround({ children }: { children: ReactNode }) {
    const [open, setOpen] = useState(false);
    useEffect(() => {
        const show = () => setOpen(true);
        window.addEventListener(OPEN_FEEDBACK, show);
        return () => window.removeEventListener(OPEN_FEEDBACK, show);
    }, []);
    return (
        <>
            {children}
            <FeedbackDialog open={open} onOpenChange={setOpen} />
        </>
    );
}

type Sending = { state: 'writing' } | { state: 'sending' } | { state: 'sent' } | { state: 'failed'; message: string; nextStep: string | null };

export function FeedbackDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
    const client = useClient();
    const [kind, setKind] = useState<FeedbackKind>('general');
    const [message, setMessage] = useState('');
    const [sending, setSending] = useState<Sending>({ state: 'writing' });
    // Each time it opens, a new note.
    useEffect(() => {
        if (!open) return;
        setKind('general');
        setMessage('');
        setSending({ state: 'writing' });
    }, [open]);

    const send = async () => {
        const text = message.trim();
        if (!text || sending.state === 'sending') return;
        setSending({ state: 'sending' });
        try {
            await feedback(text, { kind, client });
            setSending({ state: 'sent' });
        } catch (error) {
            if (!(error instanceof NoClickError)) throw error;
            // The SDK's own words name NoClick's API; here it is the app's server that couldn't be reached.
            if (error instanceof APIConnectionError) setSending({ state: 'failed', message: 'This page couldn’t reach the app’s server.', nextStep: 'Check your connection, then try again.' });
            else setSending({ state: 'failed', message: error.message, nextStep: error.nextStep });
        }
    };

    if (sending.state === 'sent') {
        return (
            <ShellDialog
                open={open}
                onOpenChange={onOpenChange}
                title="Sent"
                description="Thanks: it reaches the NoClick team as it is."
                mark={<MessageSquarePlus className="h-5 w-5" strokeWidth={1.75} />}
                footer={
                    <button type="button" className={BUTTON_PRIMARY} onClick={() => onOpenChange(false)}>
                        Done
                    </button>
                }
            />
        );
    }
    return (
        <ShellDialog
            open={open}
            onOpenChange={onOpenChange}
            title="Send feedback"
            description="Tell the NoClick team what’s working or what’s broken."
            mark={<MessageSquarePlus className="h-5 w-5" strokeWidth={1.75} />}
            onSubmit={(e) => {
                e.preventDefault();
                void send();
            }}
            footer={
                <>
                    <button type="button" className={BUTTON_GHOST} onClick={() => onOpenChange(false)}>
                        Cancel
                    </button>
                    <button type="submit" className={BUTTON_PRIMARY} disabled={!message.trim() || sending.state === 'sending'}>
                        {sending.state === 'sending' ? 'Sending…' : 'Send'}
                    </button>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                <div className="flex gap-1.5" role="radiogroup" aria-label="What it is">
                    {KINDS.map(({ kind: k, label, icon: Icon }) => (
                        <button
                            key={k}
                            type="button"
                            role="radio"
                            aria-checked={kind === k}
                            onClick={() => setKind(k)}
                            className={cn(
                                'flex h-7 items-center gap-1.5 rounded-full px-3 text-xs transition-colors',
                                kind === k ? 'bg-primary text-primary-foreground' : 'bg-foreground/[0.05] text-foreground/75 hover:bg-foreground/[0.09] hover:text-foreground'
                            )}
                        >
                            <Icon className="h-3.5 w-3.5" />
                            {label}
                        </button>
                    ))}
                </div>
                <Textarea
                    aria-label="Your note"
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                    onKeyDown={(e) => {
                        if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') void send();
                    }}
                    placeholder={kind === 'bug' ? 'What went wrong? Steps to reproduce help a lot.' : 'What’s on your mind?'}
                    maxLength={4000}
                    className="min-h-[7rem]"
                />
                {sending.state === 'failed' && (
                    <p role="alert" className="text-[13px] text-red-600 dark:text-red-400">
                        {sending.message}
                        {sending.nextStep ? ` ${sending.nextStep}` : ''}
                    </p>
                )}
            </div>
        </ShellDialog>
    );
}
