// What stands in the connect slots (`connect.app`, `connect.model` in ./slots.ts) when no host fills them: an account
// is connected at its connect page on NoClick, in a new tab, with the platform client the screen drawing it reads with.
import { useEffect, useRef, useState, type ComponentProps, type ReactNode } from 'react';
import { ExternalLink, Loader2 } from 'lucide-react';
import { Connection, type NoClick } from 'noclick';
import { toast } from 'sonner';
import { openTabForLater } from '@/lib/oauthPopup';
import { errorText } from '@/screens/console/pages/resources/shared';
import { BUTTON_GHOST, BUTTON_PRIMARY } from '@/ui/buttons';
import { ShellDialog } from '@/ui/ShellDialog';
import { cn } from '@/ui/utils';
import type { AppConnecting, ModelConnectProps } from './slots';

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

/** Waits on a connect page in another tab, saying so; the account that lands is handed on. */
function LinkConnect({ title, description, start, onConnected, onClose, extra }: { title: string; description: string; start: () => Promise<Connection>; onConnected: (credentialId: string) => void; onClose: () => void; extra?: ReactNode }) {
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
        start().then(
            (connection) => {
                if (!live.current) return;
                onConnected(connection.id.replace(/^credential:/, ''));
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
