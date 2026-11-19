// An MCP server NoClick hosts that the coordinator made (or read back) for the owner's own agent, connected on its card:
// the agent the owner named in what they asked (else the one that connected, else theirs to pick), its steps with the
// server's link to copy, and whether it has connected, pushed the moment it does. The same steps and status a
// workflow's hosted link shows on its setup card. Once a client has listed its tools, the card opens as a receipt; an
// older card about the same server is one line.
import { useEffect, useState } from 'react';
import { RotateCw } from 'lucide-react';
import { useDrawsCanvas } from '@/screens/chat/cards/canvases';
import { InlineCard, PILL_PRIMARY, PILL_QUIET, Receipt, Status, listOf } from '@/ui/chat/primitives';
import { useTurnAsked } from './toolCardRegistry';
import { NodeMark } from '@/ui/primitives';
import type { ClientGuide } from '@/ui/MCPSetupModal';
import { servedToolName, useMcpServerConnect } from './useMcpServerConnect';
import { mcpClientNamedIn } from '@/lib/mcpQuickSteps';
import type { CoordinatorToolCall } from '@/lib/toolCalls';
import { describeClient } from '@/lib/mcpConnectState';
import { cn } from '@/ui/utils';
import { mcpServerCanvas, mcpServerOf } from './cardMatchers';
import { ClientTile, CopyButton, McpClientSteps, McpConnectStatus, guideFor, useFolded } from './McpConnectSteps';

/** "Get subreddit posts" for "reddit.get_subreddit_posts". */
function toolLabel(name: string): string {
    const words = (name.split('.').pop() ?? name).replace(/_/g, ' ');
    return words.charAt(0).toUpperCase() + words.slice(1);
}

function McpServerConnect({ serverId, asked }: { serverId: string; asked: string | null }) {
    const [client, setClient] = useState<ClientGuide | undefined>(() => guideFor(mcpClientNamedIn(asked)?.key));
    const [renewing, setRenewing] = useState<'ask' | 'busy' | null>(null);
    const [renewError, setRenewError] = useState<string | null>(null);
    const [known, setKnown] = useState(false);
    const [done, setDone] = useState(false);
    const [folded, setFolded] = useFolded(known, done);
    // A connection that has worked stops reading once it folds; open, it follows the server.
    const { server, status, state, gone, renew } = useMcpServerConnect(serverId, { enabled: !folded });
    useEffect(() => {
        if (!status) return;
        setKnown(true);
        setDone(!!status.first_tools_at);
    }, [status]);
    // With no agent named, the one that connected.
    const connectedAs = status?.client_name;
    useEffect(() => {
        if (connectedAs) setClient((current) => current ?? guideFor(connectedAs));
    }, [connectedAs]);

    if (gone) return <Receipt tone="info">This MCP server was deleted</Receipt>;
    if (!server) return <Status state="working">Loading your MCP server</Status>;

    const named = client && client.key !== 'other' ? client.label : null;
    const agent = named ?? 'your agent';
    const tools = server.tools.map(servedToolName).filter((n): n is string => !!n).map(toolLabel);
    if (folded) {
        return (
            <Receipt
                lead={<NodeMark type="mcp-server" size="xs" />}
                action={
                    <button type="button" className={cn(PILL_QUIET, 'h-7')} onClick={() => setFolded(false)}>
                        Show
                    </button>
                }
            >
                {status?.client_name ? describeClient(state, agent) : (named ?? 'Your agent')} uses {server.name} through its private link
            </Receipt>
        );
    }

    const makeNew = async () => {
        setRenewing('busy');
        setRenewError(null);
        try {
            await renew();
        } catch (error) {
            setRenewError(error instanceof Error ? error.message : 'Could not make a new link');
        }
        setRenewing(null);
    };

    return (
        <InlineCard
            lead={<ClientTile guide={client} />}
            title={`Use ${server.name} from ${agent}`}
            meta={
                tools.length
                    ? `It serves ${listOf(tools)}. Anyone with its link can use ${tools.length === 1 ? 'it' : 'them'}, so keep it private.`
                    : 'It serves nothing yet: connect the apps it uses.'
            }
            actions={
                renewing === 'ask' ? (
                    <>
                        <span className="text-[13px] text-muted-foreground">The current link stops working at once.</span>
                        <button type="button" className={PILL_PRIMARY} onClick={() => void makeNew()}>
                            Make a new link
                        </button>
                        <button type="button" className={PILL_QUIET} onClick={() => setRenewing(null)}>
                            Cancel
                        </button>
                    </>
                ) : (
                    <>
                        <CopyButton value={server.url} label="Copy link" />
                        <button
                            type="button"
                            className={PILL_QUIET}
                            disabled={renewing === 'busy'}
                            title="Anyone with the link can use these tools as you."
                            onClick={() => setRenewing('ask')}
                        >
                            <RotateCw className={cn('h-3.5 w-3.5', renewing === 'busy' && 'animate-spin')} />
                            New link
                        </button>
                    </>
                )
            }
        >
            <div className="space-y-4">
                <McpClientSteps client={client} onPick={setClient} url={server.url} linkError={renewError} serverName={server.name} />
                {client && <McpConnectStatus client={client} agent={agent} state={state} read={!!status} next={`Ask it to use ${server.name}.`} />}
            </div>
        </InlineCard>
    );
}

export function McpServerCard({ call }: { call: CoordinatorToolCall }) {
    const server = mcpServerOf(call)!;
    const asked = useTurnAsked();
    const newest = useDrawsCanvas(call.id, mcpServerCanvas(call));
    if (!newest) {
        return (
            <Receipt tone="info" lead={<NodeMark type="mcp-server" size="xs" />}>
                {server.name ?? 'Your MCP server'} · its card is below
            </Receipt>
        );
    }
    return <McpServerConnect serverId={server.serverId} asked={asked} />;
}
