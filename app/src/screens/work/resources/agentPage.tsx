// An agent's own page under Resources → Agents, where a row opens (not the agent's chat): who it is
// (its face, where it works, the number it answers) with Open in Work; what it has cost this month, its files and its
// sessions as three figures; its one /workspace (AgentFiles, the file open beside the list); and the earlier sessions
// it can resume, each confirmed first. Drawn inside PlatformReads, which provides Work's client and the rows' leads.
import { useMemo, type ReactNode } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { countOf, fmtBytes, formatDollars } from '@/lib/formatters';
import { BUTTON_PRIMARY } from '@/ui/buttons';
import type { ResourceItem } from '@/screens/resources/model';
import { ResourcePageFrame } from '@/screens/resources/ResourceDetail';
import { Section } from '@/screens/resources/ui';
import { PAGE_TITLE } from '@/ui/titles';
import { cn } from '@/ui/utils';
import { listedAgent } from '../agents/reads';
import { useWorkClient } from '../client';
import { SessionRows, useSessionControls } from '../conversation/sessionControls';
import { AgentFiles } from '../files/AgentFiles';
import { useAgentWorkspace } from '../files/workspace';
import { openAgentInWork } from '../place';
import { useTriggers } from '../profile/reads';
import { AgentLead, useAgentLeads } from './agentsInResources';

const STAT = 'min-w-0 rounded-2xl border border-border bg-card px-4 py-3 dark:border-foreground/[0.08] dark:bg-foreground/[0.02]';

function Stat({ figure, line, testId }: { figure: ReactNode; line: ReactNode; testId: string }) {
    return (
        <div className={STAT} data-testid={testId}>
            <p className="truncate text-[17px] font-semibold tabular-nums text-foreground">{figure}</p>
            <p className="mt-0.5 truncate text-[12.5px] text-muted-foreground">{line}</p>
        </div>
    );
}

export function AgentResourcePage({ item, onBack }: { item: ResourceItem; now: string; onBack: (to: 'all' | 'kind') => void }) {
    const client = useWorkClient();
    const agent = useMemo(() => listedAgent(client, item.id), [client, item.id]);
    const working = useAgentLeads().entries.get(item.id)?.status === 'working';
    const sessions = useSessionControls(agent, item.id, item.title, working);
    const files = useAgentWorkspace(item.id).data;
    // The number it answers: the one its texts or calls come to, as its triggers name it.
    const number = useTriggers(item.id).data?.find((t) => t.summary?.number)?.summary?.number ?? null;
    const earlier = sessions.earlier.length;
    const size = files?.reduce((sum, f) => sum + f.size, 0) ?? 0;

    return (
        <ResourcePageFrame kindLabel="Agents" onBack={onBack}>
            <header className="flex flex-wrap items-center gap-4" data-testid="agent-page">
                <AgentLead item={item} size={48} />
                <div className="min-w-0 flex-1">
                    <h1 className={cn('min-w-0 break-words sm:truncate', PAGE_TITLE)}>{item.title}</h1>
                    <p className="mt-1 text-[14px] leading-snug text-muted-foreground sm:truncate">{[item.where, number && `answers ${number}`].filter(Boolean).join(' · ')}</p>
                </div>
                <button type="button" onClick={() => openAgentInWork(item.id)} className={BUTTON_PRIMARY}>
                    Open in Work
                    <ArrowUpRight className="h-4 w-4" />
                </button>
            </header>
            <div className="mt-6 grid gap-2.5 sm:grid-cols-3">
                <Stat testId="agent-spend" figure={item.price ? formatDollars(item.price.usd) : '…'} line="this month" />
                <Stat testId="agent-files-count" figure={files ? countOf(files.length, 'file') : '…'} line={files ? `${fmtBytes(size)} in its folder` : 'Reading its folder'} />
                <Stat
                    testId="agent-sessions"
                    figure={sessions.sessions ? countOf(earlier + 1, 'session') : '…'}
                    line={sessions.sessions ? `1 active, ${earlier} you can resume` : 'Reading its sessions'}
                />
            </div>
            <Section title="Files" meta="its /workspace">
                <AgentFiles agentId={item.id} name={item.title} preview="beside" />
            </Section>
            <Section title="Resume an earlier session" meta={earlier || undefined}>
                <p className="mb-2 text-[13px] text-muted-foreground">Everyone talking to {item.title} continues there. Its files don’t change.</p>
                {earlier ? <SessionRows sessions={sessions.sessions?.all ?? []} active={sessions.sessions?.active ?? null} onPick={sessions.pick} /> : <p className="text-[13.5px] text-muted-foreground">No earlier sessions yet.</p>}
            </Section>
            {sessions.dialogs}
        </ResourcePageFrame>
    );
}
