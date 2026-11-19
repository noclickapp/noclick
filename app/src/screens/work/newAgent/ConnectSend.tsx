// Send while nothing of yours runs the pick, or the account it runs on stopped working: what it asks for, by name ("Add
// an Anthropic key to start", "Reconnect OpenRouter to start", "Sign in to ChatGPT again to start"), opening the
// connect popup on it. New agent's box and a conversation's share it.
import { KeyRound, Plug, RotateCw } from 'lucide-react';
import { AccountGlyph } from './AccountChip';
import type { ConnectAsk } from './accounts';

export function ConnectSend({ ask, onClick }: { ask: ConnectAsk; onClick: () => void }) {
    return (
        <button
            type="button"
            onClick={onClick}
            aria-label={ask.send}
            data-primary="connect"
            className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full bg-foreground pl-1.5 pr-3.5 text-[13px] font-medium text-background transition-[opacity,transform] duration-150 active:scale-[0.97]"
        >
            <span aria-hidden className="grid h-5 w-5 place-items-center rounded-full bg-background/15">
                {ask.icon === 'reconnect' ? (
                    <RotateCw className="h-3 w-3" strokeWidth={2.25} />
                ) : ask.icon === 'plan' && ask.plan ? (
                    <AccountGlyph a={ask.plan} className="h-3 w-3" />
                ) : ask.icon === 'plug' ? (
                    <Plug className="h-3 w-3" strokeWidth={2.25} />
                ) : (
                    <KeyRound className="h-3 w-3" strokeWidth={2.25} />
                )}
            </span>
            <span className="max-sm:hidden">{ask.send}</span>
            <span className="sm:hidden">{ask.short}</span>
        </button>
    );
}
