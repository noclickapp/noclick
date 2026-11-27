import { useState, type ReactNode } from 'react';
import { ArrowUpRight, Check, Copy, KeyRound } from 'lucide-react';
import { ConsoleButton } from './Button';
import { ConsoleDialog } from './ConsoleDialog';

/**
 * A secret shown exactly once. Open while `secret` is set; there is no ✕,
 * Escape and outside clicks do nothing, and Done is the only exit: the parent
 * clears the secret in `onDone`, so it leaves the page with the dialog.
 */
export function RevealOnceSecret({
    secret,
    title,
    description = "This is the only time you'll see this key.",
    mark,
    aside,
    size = 'lg',
    quietDone = false,
    onDone,
    children,
}: {
    secret: string | null;
    title: ReactNode;
    description?: ReactNode;
    mark?: ReactNode;
    /** Beside Done, at the footer's start: a quiet link to where it's used. */
    aside?: ReactNode;
    size?: 'md' | 'lg';
    /** Done as a plain button, where the body's Copy is the one primary. */
    quietDone?: boolean;
    onDone: () => void;
    children: (secret: string) => ReactNode;
}) {
    return (
        <ConsoleDialog
            open={secret !== null}
            onOpenChange={() => undefined}
            dismissible={false}
            size={size}
            mark={mark}
            title={title}
            description={description}
            footer={
                <>
                    {aside && <span className="mr-auto">{aside}</span>}
                    <ConsoleButton variant={quietDone ? 'soft' : 'primary'} onClick={onDone}>
                        Done
                    </ConsoleButton>
                </>
            }
        >
            {secret !== null && children(secret)}
        </ConsoleDialog>
    );
}

/** A button that copies `value` and says so for a moment. */
function CopyValue({ value, label, primary = false }: { value: string; label: string; primary?: boolean }) {
    const [copied, setCopied] = useState(false);
    const copy = async () => {
        try {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
        } catch (err) {
            console.error('Copy failed', err);
        }
    };
    return (
        <ConsoleButton
            variant={primary ? 'primary' : 'soft'}
            className="w-full justify-center sm:w-auto"
            icon={primary ? copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" /> : undefined}
            onClick={() => void copy()}
        >
            {copied ? 'Copied' : label}
        </ConsoleButton>
    );
}

/**
 * One secret value shown once, alone: its name, the value in a box that wraps (a phone shows it whole), Copy, Copy as
 * the `.env` line it goes in, one line on where it goes, and a link to using it. The code that reads it is the docs'.
 */
export function SecretShownOnce({
    secret,
    title,
    description = 'Copy it now. NoClick keeps only a fingerprint, so it can’t show it again.',
    label,
    copyLabel,
    env,
    where,
    guide,
    onDone,
}: {
    secret: string | null;
    /** "backend-prod is ready". */
    title: ReactNode;
    /** Why it's shown once. */
    description?: ReactNode;
    /** What the value is: "Secret key", "Signing secret". */
    label: string;
    /** Its Copy button: "Copy key". */
    copyLabel: string;
    /** The variable it goes in, for "Copy as a .env line". */
    env: string;
    /** One line on where it goes. */
    where: ReactNode;
    /** The docs page on using it. */
    guide: { label: string; href: string };
    onDone: () => void;
}) {
    return (
        <RevealOnceSecret
            secret={secret}
            title={title}
            description={description}
            mark={<KeyRound aria-hidden className="h-5 w-5" />}
            size="md"
            quietDone
            aside={
                <a href={guide.href} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-[13px] text-muted-foreground transition-colors hover:text-foreground">
                    {guide.label} <ArrowUpRight aria-hidden className="h-3.5 w-3.5" />
                </a>
            }
            onDone={onDone}
        >
            {(value) => (
                <div className="flex flex-col gap-3">
                    <div>
                        <p className="m-0 mb-1.5 text-[13px] font-medium text-foreground/85">{label}</p>
                        <p data-testid="secret-shown-once" className="m-0 select-all break-all rounded-xl bg-foreground/[0.05] px-3.5 py-3 font-mono text-[13.5px] leading-relaxed text-foreground">
                            {value}
                        </p>
                    </div>
                    <div className="flex flex-col gap-2 sm:flex-row">
                        <CopyValue value={value} label={copyLabel} primary />
                        <CopyValue value={`${env}=${value}`} label="Copy as a .env line" />
                    </div>
                    <p className="m-0 text-[13px] leading-relaxed text-muted-foreground">{where}</p>
                </div>
            )}
        </RevealOnceSecret>
    );
}
