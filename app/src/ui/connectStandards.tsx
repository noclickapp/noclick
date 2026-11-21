// What stands in the connect slots (`connect.app`, `connect.model` in ./slots.ts) when no host fills them: an account
// is connected at its connect page on NoClick, in a new tab, with the platform client the screen drawing it reads with;
// a step's form draws the same in place, under its pickers.
import { useEffect, useRef, useState, type ComponentProps, type ReactNode } from 'react';
import { ExternalLink, Loader2 } from 'lucide-react';
import { Connection, type NoClick, type Verification } from 'noclick';
import { toast } from 'sonner';
import { refFor } from '@/lib/agentTools';
import { openTabForLater } from '@/lib/oauthPopup';
import { useClient } from '@/sdk/client';
import { errorText } from '@/screens/console/pages/resources/shared';
import { BUTTON_GHOST, BUTTON_PRIMARY } from '@/ui/buttons';
import { ShellDialog } from '@/ui/ShellDialog';
import { cn } from '@/ui/utils';
import type { ConnectionCheck } from '@/lib/connectionCheck';
import type { AppConnecting, InPlaceConnectProps, LandedConnection, ModelConnectProps } from './slots';

/** A connection that stopped working (a Connection, or its ref), connected again at its connect page on NoClick, in a
 *  new tab opened as it's asked for, so the browser lets it open. */
export async function reconnectByLink(client: NoClick, connection: Connection | string, title: string): Promise<void> {
    const tab = openTabForLater();
    try {
        const it = typeof connection === 'string' ? await Connection.get(connection, { client }) : connection;
        tab.go(it.connectUrl ?? (await it.request()).url);
    } catch (error) {
        tab.close();
        toast(`Couldn’t reconnect ${title}`, { description: errorText(error) });
    }
}

/** Makes a connection of `integration` (of `credentialType` where it says) and opens its connect page on NoClick in a
 *  new tab, opened as it's asked for so the browser lets it open; resolves with the connection once an account lands
 *  there. It carries no secret: the account is connected on NoClick's page. */
export async function connectByLink(client: NoClick, integration: string, credentialType?: string): Promise<Connection> {
    const tab = openTabForLater();
    try {
        const connection = await Connection.create(`${integration}-${Date.now().toString(36)}`, { client, integration, credentialType });
        tab.go(connection.connectUrl ?? (await connection.request()).url);
        return await connection.wait();
    } catch (error) {
        tab.close();
        throw error;
    }
}

/** The id of the account a connection that landed holds: what a step keeps, and what `credential:<id>` names for one
 *  connected in the app. */
function heldBy(connection: Connection): string {
    if (connection.credentialId === null) throw new Error(`${connection.name} was connected, but the API didn’t say which account it holds.`);
    return connection.credentialId;
}

/** Waits on a connect page in another tab, saying so; the connection that lands is handed on by both its names: its ref
 *  (here the name of the named connection it made, since `credential:<id>` names only an account connected in the app)
 *  and the account it holds. */
function LinkConnect({ title, description, start, onConnected, onClose, extra }: { title: string; description: string; start: () => Promise<Connection>; onConnected: (landed: LandedConnection) => void; onClose: () => void; extra?: ReactNode }) {
    const [waiting, setWaiting] = useState(false);
    const [problem, setProblem] = useState<string | null>(null);
    const live = useRef(true);
    useEffect(
        () => () => {
            live.current = false;
        },
        []
    );
    const go = () => {
        setWaiting(true);
        setProblem(null);
        start()
            .then((connection): LandedConnection => ({ ref: refFor(connection), credentialId: heldBy(connection) }))
            .then(
                (landed) => {
                    if (!live.current) return;
                    onConnected(landed);
                    onClose();
                },
                (error: unknown) => {
                    if (!live.current) return;
                    setWaiting(false);
                    setProblem(errorText(error));
                }
            );
    };
    return (
        <ShellDialog
            open
            onOpenChange={(open) => !open && onClose()}
            title={title}
            description={description}
            footer={
                <>
                    <button type="button" onClick={onClose} className={BUTTON_GHOST}>
                        Cancel
                    </button>
                    <button type="button" onClick={go} disabled={waiting} className={cn(BUTTON_PRIMARY, 'inline-flex items-center gap-1.5')}>
                        {waiting ? <Loader2 className="h-4 w-4 animate-spin" /> : <ExternalLink className="h-4 w-4" />}
                        {waiting ? 'Waiting for it on NoClick…' : 'Connect on NoClick'}
                    </button>
                </>
            }
        >
            {extra}
            {problem && <p className="text-[13px] text-red-600 dark:text-red-400">{problem}</p>}
        </ShellDialog>
    );
}

/** An app's account connected at its connect page on NoClick. */
export function AppConnectLink({ app, name, client, onConnected, onClose }: ComponentProps<AppConnecting['Connect']>) {
    const integration = app.value.replace(/^automation-/, '').replace(/-/g, '_');
    return (
        <LinkConnect
            title={`Connect ${app.label}`}
            description={`${name} gets its tools once it’s connected. It opens on NoClick in a new tab.`}
            start={() => connectByLink(client, integration, app.acceptedCredentialTypes[0])}
            onConnected={onConnected}
            onClose={onClose}
        />
    );
}

/** The AI account a model needs, connected at its connect page on NoClick (a key, or signing in with a plan). */
export function ModelConnectLink({ credentialType, integration, title, description, others, client, onOpenChange, onConnected }: ModelConnectProps) {
    if (!credentialType || !integration) return null;
    return (
        <LinkConnect
            title={title ?? 'Connect an AI account'}
            description={description ?? 'It opens on NoClick in a new tab.'}
            start={() => connectByLink(client, integration, credentialType)}
            onConnected={onConnected}
            onClose={() => onOpenChange(false)}
            extra={
                others.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                        <span className="text-[12.5px] text-muted-foreground">Or run it on</span>
                        {others.map((o) => (
                            <button key={o.key} type="button" onClick={o.onPick} className="rounded-full bg-foreground/[0.06] px-2.5 text-[12.5px] leading-6 hover:bg-foreground/[0.1]">
                                {o.label}
                            </button>
                        ))}
                    </div>
                )
            }
        />
    );
}

/** What connecting an account proved, in the words a verdict reads (null: nothing could be judged). */
export function checkOf(verification: Verification | null): ConnectionCheck | null {
    if (!verification) return null;
    return {
        reachable: verification.reachable,
        samples: verification.samples as ConnectionCheck['samples'],
        noun: verification.noun ?? undefined,
        total: verification.total,
        account_label: verification.accountLabel,
        proves: verification.proves ?? undefined,
        error: verification.error,
        hint: verification.hint,
    };
}

/** One of a step's accounts connected at its connect page on NoClick, from the step's form: a button that opens it in
 *  a new tab, then waits for the account to land there. One whose connection dropped is connected again at its own
 *  page; an app whose accounts the API doesn't connect says to connect it on NoClick. */
export function AppConnectInPlace({ app, integration, credentialType, repairs, onConnected }: InPlaceConnectProps) {
    const client = useClient();
    const [waiting, setWaiting] = useState(false);
    const [problem, setProblem] = useState<string | null>(null);
    const live = useRef(true);
    useEffect(
        () => () => {
            live.current = false;
        },
        []
    );
    if (!integration) {
        return <p className="text-[13px] leading-relaxed text-muted-foreground">{app}’s accounts aren’t connected through the API: connect one on NoClick.</p>;
    }
    const go = () => {
        if (repairs) {
            void reconnectByLink(client, `credential:${repairs}`, app);
            return;
        }
        setWaiting(true);
        setProblem(null);
        connectByLink(client, integration, credentialType).then(
            (connection) => {
                if (!live.current) return;
                setWaiting(false);
                onConnected({ id: heldBy(connection), name: connection.name, credential_type: connection.credentialType ?? credentialType ?? '' }, checkOf(connection.verification));
            },
            (error: unknown) => {
                if (!live.current) return;
                setWaiting(false);
                setProblem(errorText(error));
            }
        );
    };
    return (
        <div className="space-y-2" data-testid="connect-in-place">
            <p className="text-[13px] leading-relaxed text-muted-foreground">
                {repairs ? `Connect your ${app} account again on NoClick, in a new tab.` : `Connect a ${app} account on NoClick, in a new tab: the step gets it once it’s connected.`}
            </p>
            <button type="button" onClick={go} disabled={waiting} className={cn(BUTTON_PRIMARY, 'inline-flex items-center gap-1.5')}>
                {waiting ? <Loader2 className="h-4 w-4 animate-spin" /> : <ExternalLink className="h-4 w-4" />}
                {waiting ? 'Waiting for it on NoClick…' : repairs ? 'Reconnect on NoClick' : 'Connect on NoClick'}
            </button>
            {problem && <p className="text-[13px] text-red-600 dark:text-red-400">{problem}</p>}
        </div>
    );
}
