// The MCP servers it has as tools, as the conversation in view last saw them: each one up, connecting or failed with its
// error, how many tools it gave, and Reconnect where the harness can redo it (Codex reloads them all; Hermes and
// OpenClaw connect theirs every turn, so it says so instead). Read again on the frame a turn's MCP gate or a reconnect sends.
import { useState } from 'react';
import { toast } from 'sonner';
import { Plug, RotateCw } from 'lucide-react';
import { Agent, type ToolServer, type ToolServers as Servers } from 'noclick';
import { cn } from '@/ui/utils';
import { useWorkClient } from '../client';
import { agoText } from '../agents/states';
import { rereadToolServers, useToolServers } from './reads';

const PILL =
    'inline-flex h-6 shrink-0 items-center gap-1 rounded-full px-2 text-[12px] font-medium text-foreground/85 transition-colors hover:bg-foreground/[0.06] hover:text-foreground disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

/** The mcp-server steps its workflow has (`added_in_app`), named before any conversation has connected them. */
function addedServers(agent: Agent): { id: string; name: string }[] {
    const added = (agent.raw as { added_in_app?: unknown }).added_in_app;
    return (Array.isArray(added) ? added : []).filter((s): s is { id: string; name: string } => !!s && typeof s === 'object' && (s as { type?: unknown }).type === 'mcp-server');
}

function Dot({ status }: { status: ToolServer['status'] }) {
    if (status === 'connecting') return <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-foreground/35 motion-reduce:animate-none" />;
    return <span className={cn('h-2 w-2 shrink-0 rounded-full', status === 'connected' ? 'bg-emerald-500' : 'bg-red-500')} />;
}

const toolsText = (n: number | null) => (n === null ? '' : n === 1 ? '1 tool' : `${n} tools`);

/** A tool server's Reconnect pill: its handshake done again in the running harness (`all` for every server). */
export function ReconnectPill({ busy, disabled, all, onClick, className }: { busy: boolean; disabled?: boolean; all?: boolean; onClick: () => void; className?: string }) {
    return (
        <button
            type="button"
            disabled={disabled || busy}
            onClick={(e) => {
                // A row that opens a page holds it.
                e.stopPropagation();
                onClick();
            }}
            className={cn(PILL, className)}
        >
            <RotateCw className={cn('h-3 w-3', busy && 'animate-spin motion-reduce:animate-none')} strokeWidth={2} />
            {busy ? 'Reconnecting…' : all ? 'Reconnect all' : 'Reconnect'}
        </button>
    );
}

export function ToolServers({ agent, conversation }: { agent: Agent; conversation: string | null }) {
    const client = useWorkClient();
    const read = useToolServers(agent.id, conversation);
    const [reconnecting, setReconnecting] = useState<string | null>(null);
    const added = addedServers(agent);
    const servers = read.data?.servers ?? [];
    const named = servers.length ? null : added;
    if (!servers.length && !added.length) return null;

    const reconnect = async (data: Servers, name: string) => {
        setReconnecting(name);
        try {
            await Agent.fromId(agent.id, { client }).conversation(conversation!).reconnectToolServer(name);
        } catch (error) {
            toast(data.reconnect.scope === 'all' ? 'Couldn’t reconnect its tool servers' : `Couldn’t reconnect ${name}`, { description: error instanceof Error ? error.message : String(error) });
        } finally {
            setReconnecting(null);
            rereadToolServers(agent.id, conversation!);
        }
    };
    const data = read.data;
    const failed = servers.filter((s) => s.status === 'failed');
    const each = data?.reconnect.available && data.reconnect.scope === 'server';
    const all = data?.reconnect.available && data.reconnect.scope === 'all';

    return (
        <section className="mt-6" data-testid="tool-servers">
            <h3 className="flex items-baseline gap-2 text-xs font-medium text-muted-foreground">
                Tool servers
                {data?.source === 'last_turn' && data.checkedAt && <span className="font-normal">· as of its last turn, {agoText(Date.now() - data.checkedAt.getTime())}</span>}
            </h3>
            <ul className="mt-1.5 space-y-1">
                {named
                    ? named.map((s) => (
                          <li key={s.id} className="flex items-center gap-2.5 py-1 text-sm">
                              <Plug className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={1.75} />
                              <span className="min-w-0 truncate">{s.name}</span>
                          </li>
                      ))
                    : servers.map((s) => (
                          <li key={s.name} className="py-1" data-server={s.name} data-status={s.status}>
                              <div className="flex items-center gap-2.5 text-sm">
                                  <Dot status={s.status} />
                                  <span className="min-w-0 flex-1 truncate">{s.name}</span>
                                  {s.status === 'connecting' ? (
                                      <span className="shrink-0 text-[12.5px] text-muted-foreground">Connecting…</span>
                                  ) : s.status === 'failed' && each ? (
                                      <ReconnectPill busy={reconnecting === s.name} disabled={reconnecting !== null} onClick={() => void reconnect(data!, s.name)} className="-mr-2" />
                                  ) : (
                                      <span className="shrink-0 text-[12.5px] tabular-nums text-muted-foreground">{toolsText(s.toolCount)}</span>
                                  )}
                              </div>
                              {s.error && <p className="ml-[18px] mt-0.5 line-clamp-2 text-[12.5px] leading-snug text-red-600 dark:text-red-400">{s.error}</p>}
                          </li>
                      ))}
            </ul>
            {failed.length > 0 && all && <ReconnectPill all busy={reconnecting !== null} onClick={() => void reconnect(data!, failed[0].name)} className="-ml-2 mt-1" />}
            {failed.length > 0 && data && !data.reconnect.available && data.reconnect.why && <p className="mt-1 text-[12.5px] leading-snug text-muted-foreground">{data.reconnect.why}</p>}
            {named && conversation && data?.source === 'none' && <p className="mt-1 text-[12.5px] leading-snug text-muted-foreground">They connect when it next works here.</p>}
            {read.error !== undefined && <p className="mt-1 text-[12.5px] leading-snug text-muted-foreground">Couldn’t read whether they’re connected.</p>}
        </section>
    );
}
