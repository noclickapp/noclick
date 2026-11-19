// The tool servers a move from a laptop couldn't bring the sign-in of, because the laptop signed in to them in a
// browser: read from the move's `arrived.carried`. Each is signed in to again here with NoClick's own MCP sign-in
// (whoever shows Work signs in: `TOOL_SERVER_SIGN_IN`, discovered as it's shown, so the click itself opens the provider's page), and the credential that
// leaves is handed to the agent's step for it (`AgentMove.connectSignIn`). The agent's profile and a space's Resources
// both list them.
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { AgentMove, NotFound, type JsonObject, type NoClick } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import { BUTTON_SECONDARY } from '@/ui/buttons';
import { useSlot } from '@/slots';
import { TOOL_SERVER_SIGN_IN } from '../slots';
import { cn } from '@/ui/utils';
import { useWorkClient } from '../client';
import { useWorkV1 } from '../agents/reads';

export interface BrowserSignIn {
    moveId: string;
    /** The agent the move made. */
    agentId: string | null;
    /** The computer it moved from. */
    host: string | null;
    /** The tool server, by the name the agent knows it by. */
    name: string;
    url: string;
    needsSignIn: boolean;
}

/** A finished move, or null once it's gone (moves are kept 7 days). */
export async function readMove(client: NoClick, moveId: string): Promise<AgentMove | null> {
    try {
        return await AgentMove.fromId(moveId, { client }).refresh();
    } catch (error) {
        if (error instanceof NotFound) return null;
        throw error;
    }
}

/** The browser sign-ins a move carried: a tool server entry with its URL and no secrets of its own. */
export function browserSignInsOf(move: AgentMove): BrowserSignIn[] {
    return move.arrived.carried.flatMap((c: JsonObject) => {
        const to = c.to as JsonObject | undefined;
        if (typeof to?.tool_server !== 'string' || typeof c.url !== 'string' || Array.isArray(c.secrets)) return [];
        return [{ moveId: move.id, agentId: move.agentId, host: move.source?.host || null, name: String(c.name), url: c.url, needsSignIn: c.needs_sign_in === true }];
    });
}

/** The browser sign-ins of several moves (a space's agents'). */
export function useMovesSignIns(moveIds: readonly string[]) {
    const ids = [...new Set(moveIds)].sort();
    return useWorkV1(ids.length ? `work:moves:sign-ins:${ids.join(',')}` : null, async (client) => (await Promise.all(ids.map((id) => readMove(client, id)))).flatMap((m) => (m ? browserSignInsOf(m) : [])));
}

/** Reads every move again (the profile's `work:move:<id>:…` and the lists' `work:moves:…`). */
export const rereadMoves = () => invalidateV1('work:move');

/** Signing a browser sign-in in here: ready once its server's OAuth is discovered, a problem in words if there is one,
 *  and connect, which runs the sign-in and hands the credential to the agent's step. */
export function useBrowserSignIn(signIn: BrowserSignIn) {
    const client = useWorkClient();
    const [handing, setHanding] = useState(false);
    const oauth = useSlot(TOOL_SERVER_SIGN_IN)({
        onCredentialCreated: (credentialId) => {
            setHanding(true);
            // The agent's step for it takes the credential, stamped as moved from the laptop.
            void AgentMove.fromId(signIn.moveId, { client })
                .connectSignIn(signIn.name, credentialId)
                .then(rereadMoves)
                .catch((error) => toast(`Couldn’t sign it in to ${signIn.name}`, { description: error instanceof Error ? error.message : String(error) }))
                .finally(() => setHanding(false));
        },
    });
    const { discover } = oauth;
    useEffect(() => {
        if (signIn.needsSignIn) void discover(signIn.url);
    }, [signIn.needsSignIn, signIn.url, discover]);
    const refused = oauth.discoveryResult && !oauth.discoveryResult.requires_oauth ? 'It doesn’t sign in in a browser, so it can’t be connected here.' : null;
    return {
        ready: !!oauth.discoveryResult?.requires_oauth && !oauth.isConnecting && !handing,
        connecting: oauth.isConnecting || handing,
        problem: oauth.error ?? refused,
        connect: () => void oauth.connect(signIn.url, signIn.name),
    };
}

/** Its Connect pill. */
export function ConnectSignIn({ state }: { state: ReturnType<typeof useBrowserSignIn> }) {
    return (
        <button
            type="button"
            disabled={!state.ready}
            onClick={(e) => {
                // A row that opens a page holds it.
                e.stopPropagation();
                state.connect();
            }}
            className={cn(BUTTON_SECONDARY, 'h-7 shrink-0 px-3 text-[12.5px]')}
        >
            {state.connecting ? 'Connecting…' : 'Connect'}
        </button>
    );
}
