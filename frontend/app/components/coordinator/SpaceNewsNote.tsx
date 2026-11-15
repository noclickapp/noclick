// A space's news as NoClick passed it on (an alert from the space's NoClick, an answer to a question asked there):
// which space it's from, by the label its NoClick goes by, opening that space's NoClick channel in Work, over what
// NoClick said.
import { ChevronRight } from 'lucide-react';
import { MarkdownRenderer } from '~/components/chat/MarkdownRendererLazy';
import { LogoMark, MARK_IN_A_SHAPE } from '~/components/shared/LogoMark';
import type { AgentChatMessage } from '~/hooks/useAgentChat';
import { navigateToTab, WORK_NOCLICK_CHANNEL } from '~/lib/navigation';
import { cn } from '~/lib/utils';

export function SpaceNewsNote({ msg }: { msg: AgentChatMessage & { space: { id: string; label: string } } }) {
    const open = () =>
        navigateToTab('work', { space: msg.space.id, show: null, channel: WORK_NOCLICK_CHANNEL, thread: null, agent: null, panel: null, machine: null, res: null, item: null });
    return (
        <div data-testid="space-news">
            <button
                type="button"
                onClick={open}
                className="group -ml-0.5 mb-1.5 inline-flex max-w-full items-center gap-2 rounded-full py-0.5 pr-2 text-[13px] font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
                <span aria-hidden className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-foreground/[0.07]">
                    <LogoMark alt="" className={cn('h-2.5 w-2.5', MARK_IN_A_SHAPE)} />
                </span>
                <span className="truncate">{msg.space.label}</span>
                <ChevronRight className="h-3.5 w-3.5 shrink-0 opacity-60 transition-transform group-hover:translate-x-0.5" strokeWidth={2} />
            </button>
            <MarkdownRenderer content={msg.text} />
        </div>
    );
}
