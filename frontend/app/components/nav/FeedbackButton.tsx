// Navbar button that opens a small popover where users can type and instantly
// submit feedback or a bug report. Sends the `feedback:submit` socket event
// (persisted to the user_feedback table). Added to give users a frictionless,
// in-app feedback channel without leaving whatever they're working on.
//
// Fully keyboard-driven: the "H then H" leader chord opens it (via the
// OPEN_FEEDBACK_EVENT dispatched from useLeaderShortcuts), ⌘/Ctrl+Enter submits,
// and Escape closes ONLY this popover. Escape stacking: the content carries
// role="dialog" so FlowCanvas's capture-phase Escape handler defers to it, and
// onEscapeKeyDown stops propagation so the close doesn't also reach Dashboard's
// handler (which would close the chat sidebar / flow helper).

import { useEffect, useRef, useState } from 'react';
import {
    MessageSquarePlus,
    Bug,
    Lightbulb,
    MessageCircle,
    Loader2,
} from 'lucide-react';
import { toast } from 'sonner';
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from '~/components/ui/popover';
import { KeyHint, SequenceKeyHint } from '~/components/shared/KeyHint';
import { ShortcutTooltip } from '~/components/shared/ShortcutTooltip';
import { sendEventAsync } from '~/lib/socket-sender';
import { SubmitFeedbackRequest } from '~/types/socket-events.generated';
import { OPEN_FEEDBACK_EVENT } from '~/lib/shortcuts';
import { useAnalytics } from '~/lib/analytics';
import { cn } from '~/lib/utils';

type FeedbackType = 'general' | 'bug' | 'idea';

const TYPES: { key: FeedbackType; label: string; icon: typeof Bug }[] = [
    { key: 'general', label: 'Feedback', icon: MessageCircle },
    { key: 'bug', label: 'Bug', icon: Bug },
    { key: 'idea', label: 'Idea', icon: Lightbulb },
];

export function FeedbackButton() {
    const { logActivity } = useAnalytics();
    const [open, setOpen] = useState(false);
    const [type, setType] = useState<FeedbackType>('general');
    const [message, setMessage] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const textareaRef = useRef<HTMLTextAreaElement>(null);

    // Open when the "H then H" leader chord fires (useLeaderShortcuts dispatches this).
    useEffect(() => {
        const openPopover = () => {
            setOpen(true);
            logActivity('feedback_opened', { source: 'shortcut' });
        };
        window.addEventListener(OPEN_FEEDBACK_EVENT, openPopover);
        return () =>
            window.removeEventListener(OPEN_FEEDBACK_EVENT, openPopover);
    }, [logActivity]);

    // Auto-grow the textarea with its content, up to its max-height — past that
    // it scrolls (with the shared subtle scrollbar). Runs on open too so it
    // resets to the min height each time the popover is shown.
    useEffect(() => {
        const el = textareaRef.current;
        if (!el) return;
        el.style.height = 'auto';
        el.style.height = `${el.scrollHeight}px`;
    }, [message, open]);

    const reset = () => {
        setMessage('');
        setType('general');
    };

    const handleSubmit = async () => {
        const text = message.trim();
        if (!text || submitting) return;
        setSubmitting(true);
        // Shared props so the success and failure events line up in PostHog.
        const analyticsProps = { type, message_length: text.length };
        try {
            const response = (await sendEventAsync(
                SubmitFeedbackRequest.create({
                    request_id: crypto.randomUUID(),
                    message: text,
                    feedback_type: type,
                    page_url:
                        typeof window !== 'undefined'
                            ? window.location.href
                            : null,
                    metadata:
                        typeof navigator !== 'undefined'
                            ? { user_agent: navigator.userAgent }
                            : null,
                })
            )) as { success?: boolean; error?: string };
            if (response?.error) throw new Error(response.error);
            logActivity('feedback_submitted', analyticsProps);
            toast.success('Thanks for the feedback!');
            reset();
            setOpen(false);
        } catch (error) {
            const errorMessage =
                error instanceof Error ? error.message : String(error);
            console.error('[FeedbackButton] failed to submit feedback:', error);
            // Capture the failure (with context) so the session is findable in
            // PostHog and its replay shows what led up to the error.
            logActivity('feedback_submit_failed', {
                ...analyticsProps,
                error: errorMessage,
            });
            toast.error('Could not send feedback. Please try again.');
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <Popover
            open={open}
            onOpenChange={(o) => {
                setOpen(o);
                if (o) logActivity('feedback_opened', { source: 'button' });
                else reset();
            }}
        >
            <ShortcutTooltip keys={['H', 'H']}>
                <PopoverTrigger asChild>
                    <button className="hidden md:flex items-center gap-2 rounded-lg bg-secondary dark:bg-foreground/[0.06] px-2.5 py-1.5 text-sm text-foreground/80 transition-colors hover:bg-accent dark:hover:bg-foreground/[0.1]">
                        <MessageSquarePlus className="h-4 w-4 text-muted-foreground dark:text-zinc-500" />
                        Feedback
                    </button>
                </PopoverTrigger>
            </ShortcutTooltip>
            <PopoverContent
                role="dialog"
                aria-label="Send feedback"
                align="end"
                sideOffset={8}
                collisionPadding={16}
                // Move focus straight into the textarea on open (instead of the
                // jsx-a11y-flagged autoFocus prop) so it's instantly typeable.
                onOpenAutoFocus={(e) => {
                    e.preventDefault();
                    textareaRef.current?.focus();
                }}
                // Let Radix close the popover but stop the Escape from reaching
                // Dashboard's handler (so it doesn't also close the chat sidebar
                // or flow helper). Don't preventDefault — that would keep it open.
                onEscapeKeyDown={(e) => e.stopPropagation()}
                // Don't yank focus back to the trigger on close — that lit up a
                // focus-visible ring on the navbar button after Escape.
                onCloseAutoFocus={(e) => e.preventDefault()}
                className="w-[calc(100vw-2rem)] rounded-xl border border-foreground/10 bg-popover dark:bg-[#0a0a0b] p-3 text-foreground shadow-2xl sm:w-96"
            >
                <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-foreground">
                        Send feedback
                    </h3>
                    <SequenceKeyHint keys={['H', 'H']} />
                </div>
                <p className="mt-0.5 text-xs text-foreground/60 dark:text-foreground/40">
                    Tell us what&apos;s working or what&apos;s broken.
                </p>

                <div className="mt-2 flex gap-1.5">
                    {TYPES.map(({ key, label, icon: Icon }) => (
                        <button
                            key={key}
                            type="button"
                            onClick={() => setType(key)}
                            className={cn(
                                'flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs transition-colors',
                                type === key
                                    ? 'bg-primary text-primary-foreground'
                                    : 'bg-secondary text-foreground/75 hover:bg-accent hover:text-foreground dark:bg-foreground/[0.04] dark:text-foreground/60 dark:hover:bg-foreground/[0.08]'
                            )}
                        >
                            <Icon className="h-3.5 w-3.5" />
                            {label}
                        </button>
                    ))}
                </div>

                <textarea
                    ref={textareaRef}
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                    onKeyDown={(e) => {
                        if ((e.metaKey || e.ctrlKey) && e.key === 'Enter')
                            handleSubmit();
                    }}
                    placeholder={
                        type === 'bug'
                            ? 'What went wrong? Steps to reproduce help a lot.'
                            : "What's on your mind?"
                    }
                    className="scrollbar-subtle mt-2 max-h-[15rem] min-h-[7rem] w-full resize-none overflow-y-auto rounded-lg border border-border bg-card dark:border-foreground/[0.08] dark:bg-foreground/[0.03] px-3 py-2.5 text-sm text-foreground placeholder:text-foreground/30 focus:border-foreground/25 focus:outline-none"
                />

                <div className="mt-2 flex justify-end">
                    <button
                        type="button"
                        onClick={handleSubmit}
                        disabled={!message.trim() || submitting}
                        className="flex items-center gap-2 rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                        {submitting ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : null}
                        Send
                        <KeyHint
                            keys={['mod', 'enter']}
                            kbdClassName="bg-primary-foreground/10 text-primary-foreground/60"
                        />
                    </button>
                </div>
            </PopoverContent>
        </Popover>
    );
}
