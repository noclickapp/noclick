// "Powered by NoClick" referral badge on public shared-agent pages — the
// growth loop: every shared agent page links back to NoClick with utm
// attribution. Rendered inline in the composer's hint row (via
// AgentChatComposer footerEnd) so it costs no vertical space.
//
// The link id is deliberately NOT carried. It is the capability: whoever holds
// it can talk to the agent, billed to its owner. Putting it in an outbound href
// hands it to our own logs on every click, and to anything in between.

import { LogoMark } from '~/components/shared/LogoMark';

export function PoweredByBadge() {
    return (
        <a
            href="https://noclick.com/?utm_source=agent-share&utm_medium=badge"
            target="_blank"
            rel="noopener noreferrer"
            data-testid="agent-share-powered-by"
            className="inline-flex items-center gap-1.5 whitespace-nowrap text-[11px] text-muted-foreground/70 dark:text-zinc-500 hover:text-muted-foreground dark:hover:text-zinc-300 border border-border hover:border-foreground/20 rounded-full px-2.5 py-1 transition-colors"
        >
            Powered by
            <span className="inline-flex items-center gap-1 font-semibold text-muted-foreground dark:text-zinc-300">
                <LogoMark alt="" className="w-3 h-3" aria-hidden />
                NoClick
            </span>
        </a>
    );
}
