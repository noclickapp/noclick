// The waiting step of a device-code sign-in (ChatGPT, GitHub Copilot, xAI): the
// code to enter, where to enter it, and a way to say it's been approved. One
// panel for every provider that signs in this way, and the line every sign-in
// shows while it starts.
import { Loader2 } from 'lucide-react';
import { Button } from '~/components/ui/button';

export function DeviceCodePanel({
    provider,
    userCode,
    verificationUrl,
    polling,
    onCancel,
    onApproved,
}: {
    provider: string;
    userCode?: string;
    verificationUrl?: string;
    polling: boolean;
    onCancel: () => void;
    onApproved: () => void;
}) {
    return (
        <div className="space-y-3" data-testid="device-code-panel">
            <div>
                <p className="text-[14.5px] font-medium text-foreground">Finish signing in with {provider}</p>
                <p className="mt-0.5 text-[13px] leading-snug text-muted-foreground">
                    Enter this code on{' '}
                    {verificationUrl ? (
                        <a
                            href={verificationUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="font-medium text-foreground underline decoration-foreground/30 underline-offset-4 transition-colors hover:decoration-foreground"
                        >
                            {provider}’s sign-in page
                        </a>
                    ) : (
                        `${provider}’s sign-in page`
                    )}
                    .
                </p>
            </div>
            <div className="select-all rounded-xl bg-foreground/[0.05] py-3 text-center font-mono text-2xl font-semibold tracking-[0.2em] text-foreground">{userCode}</div>
            <div className="flex flex-wrap items-center justify-between gap-3">
                <span className="inline-flex items-center gap-2 text-[12.5px] text-muted-foreground">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    {polling ? 'Checking…' : 'Waiting for you to approve…'}
                </span>
                <div className="flex items-center gap-1">
                    <button type="button" onClick={onCancel} className="inline-flex h-9 items-center rounded-full px-3 text-[13px] text-muted-foreground transition-colors hover:text-foreground">
                        Cancel
                    </button>
                    <Button type="button" size="sm" onClick={onApproved} disabled={polling}>
                        I’ve approved it
                    </Button>
                </div>
            </div>
        </div>
    );
}

/** The moment between pressing a sign-in button and the provider answering. */
export function SignInStarting() {
    return (
        <p className="flex items-center gap-2 py-2 text-[13px] text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Starting sign-in…
        </p>
    );
}
