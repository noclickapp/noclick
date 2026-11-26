// The card under the note an agents page's arrival leaves (POST /v1/agents/for_apps made the agent and its channel):
// the agent, its face and name, where it runs and where you talk to it, then a row for each thing it still needs
// (each of its apps' accounts, and its model where it had none), each with Connect, the white pill, until it's in.
// Once nothing is missing, opening its channel is the white pill, with a box under it that posts into the channel as
// you and moves you there, as a channel's card does. It follows the connections and the agent live (useAgentNeeds).
// A newer card about the same agent folds it to a line.
import { ArrowUpRight } from 'lucide-react';
import type { HarnessName } from 'noclick';
import type { JsonObject } from '@/lib/toolCalls';
import type { AgentForAppsSetupRef } from '@/lib/agentThread/thread';
import { NodeMark } from '@/ui/primitives';
import { CARD, PILL_PRIMARY, PILL_QUIET, Receipt, Row, Rows, Status } from '@/ui/chat/primitives';
import { MemberAvatar } from '@/screens/channels/avatars';
import { hueFor } from '@/screens/channels/model';
import type { ChannelMember } from '@/screens/channels/types';
import { HarnessMark } from '@/screens/work/agents/harness';
import { useAgentNeeds, type NeedRow } from '@/screens/work/agents/needs';
import { openChannelInWork } from '@/screens/work/place';
import { rememberOpened } from '@/screens/work/remember';
import { cn } from '@/ui/utils';
import { jobOf } from './agentWords';
import { ChannelReplyBox } from './ChannelCard';
import { useChannelReply } from './useChannelReply';

/** An app's mark, or the harness the model is for, in one tile, so each row's words start in line. */
function NeedLead({ row, harness }: { row: NeedRow; harness: HarnessName | null }) {
    return (
        <span className="grid h-8 w-8 place-items-center rounded-[10px] bg-foreground/[0.06] dark:bg-foreground/[0.08]">
            {row.nodeType ? <NodeMark type={row.nodeType} size="sm" /> : harness ? <HarnessMark harness={harness} className="h-4 w-4" /> : null}
        </span>
    );
}

export function AgentForAppsCard({ setup, folded }: { setup: AgentForAppsSetupRef; folded: boolean }) {
    const needs = useAgentNeeds(setup.agent_id, setup.needs);
    const reply = useChannelReply(setup.channel_id);
    const agent = needs.agent;
    const name = agent?.name ?? 'Your agent';
    const channel = reply.channel?.name ? `#${reply.channel.name}` : 'its channel';
    const member: ChannelMember = { id: setup.agent_id, kind: 'agent', name, agentId: setup.agent_id, hue: hueFor(setup.agent_id), role: agent ? jobOf(agent.raw as JsonObject) : undefined };
    const open = () => {
        rememberOpened(setup.channel_id);
        openChannelInWork(setup.channel_id);
    };

    if (reply.gone) return <Receipt tone="info">{name} was deleted, with {channel}</Receipt>;
    if (folded) {
        return (
            <Receipt
                tone="info"
                lead={<MemberAvatar member={member} size={16} />}
                action={
                    <button type="button" className={cn(PILL_QUIET, 'h-7')} onClick={open}>
                        Open {channel}
                    </button>
                }
            >
                {name}
            </Receipt>
        );
    }

    const missing = needs.rows.filter((r) => !r.connected).length;
    const where = [needs.harness && `Runs on ${needs.harness}`, `in ${channel}, your personal space`].filter(Boolean).join(' · ');
    return (
        <section className={cn(CARD, 'overflow-hidden')} data-testid="agent-for-apps-card" data-ready={needs.done ? '' : undefined}>
            <header className="flex items-start gap-3 px-4 pt-3.5">
                <span className="mt-0.5 shrink-0">
                    <MemberAvatar member={member} size={32} />
                </span>
                <div className="min-w-0 flex-1">
                    <h3 className="truncate text-[14.5px] font-medium leading-snug tracking-[-0.005em] text-foreground">{name}</h3>
                    <p className="mt-0.5 text-[13px] leading-snug text-muted-foreground">{where}</p>
                </div>
                <span className="shrink-0 pt-0.5">
                    {needs.done ? <Status state="done">Ready</Status> : missing > 0 && <Status state="idle">{`${missing} to connect`}</Status>}
                </span>
            </header>
            <div className="mx-4 mt-3 border-t border-border dark:border-foreground/[0.07]" />
            <Rows className="px-4">
                {needs.rows.map((row) => (
                    <Row
                        key={row.key}
                        testId={`agent-for-apps-need-${row.kind}`}
                        lead={<NeedLead row={row} harness={agent?.harness ?? null} />}
                        title={row.title}
                        detail={row.line}
                        aside={
                            row.connected ? (
                                <Status state="done">
                                    <span className="max-sm:hidden">Connected</span>
                                </Status>
                            ) : (
                                <button type="button" className={PILL_PRIMARY} disabled={!row.ready} onClick={row.connect} aria-label={`Connect ${row.title}`}>
                                    Connect
                                </button>
                            )
                        }
                    />
                ))}
            </Rows>
            <div className="flex flex-wrap items-center gap-2 px-4 pb-3.5 pt-2">
                <button type="button" className={needs.done ? PILL_PRIMARY : cn(PILL_QUIET, '-ml-3')} onClick={open} data-testid="agent-for-apps-open">
                    Open {channel}
                    <ArrowUpRight className="h-3.5 w-3.5" />
                </button>
            </div>
            {needs.done && <ChannelReplyBox reply={reply} to={member} placeholder={`Tell ${name} what to work on`} onSent={open} className="-mt-1.5 px-3" />}
            {needs.dialog}
        </section>
    );
}
