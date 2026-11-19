// What stands in Work's slots (slots.ts) when no host fills them: each works on the platform API alone.
import { useContext, useEffect, useMemo, useRef, useState, type ComponentProps, type ReactNode } from 'react';
import { ExternalLink, FileText, Loader2 } from 'lucide-react';
import { Connection, type NoClick } from 'noclick';
import { toast } from 'sonner';
import { fileKindOf } from '@/lib/embedKind';
import { openTabForLater } from '@/lib/oauthPopup';
import { useV1 } from '@/sdk/useV1';
import { ConsoleContext } from '@/screens/console/hooks/useConsole';
import { addFundsUrl, NOCLICK_SITE } from '@/screens/console/lib/site';
import { errorText } from '@/screens/console/pages/resources/shared';
import { FileGlyph } from '@/screens/resources/FileGlyph';
import type { PreviewParts } from '@/screens/resources/FilePreview';
import type { FileEntry } from '@/screens/resources/files';
import { StandardMarkdown } from '@/screens/resources/slotStandards';
import { BUTTON_GHOST, BUTTON_PRIMARY } from '@/ui/buttons';
import { ShellDialog } from '@/ui/ShellDialog';
import { cn } from '@/ui/utils';
import { useWorkClient } from './client';
import type {
    AddFundsProps,
    AppConnecting,
    ModelConnectProps,
    ToolApp,
    ToolServerSignIn,
    TurnCardParts,
    WorkAddress,
} from './slots';

// ── an agent's turns ───────────────────────────────────────────────────────

function Unchanged({ children }: { children: ReactNode }) {
    return <>{children}</>;
}

export const NO_CARDS: TurnCardParts = { Provider: Unchanged, Cards: () => null };

/** A file in a message, as a card that opens it in a new tab. */
export function LinkedFileCard({ name, url }: { name: string; url: string }) {
    return (
        <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            title={name}
            data-testid="agent-chat-file-attachment"
            className="flex max-w-[260px] items-center gap-2.5 rounded-2xl bg-card py-2 pl-2 pr-3.5 no-underline ring-1 ring-inset ring-border transition-colors hover:bg-foreground/[0.03] dark:bg-foreground/[0.03] dark:ring-foreground/[0.08] dark:hover:bg-foreground/[0.05]"
        >
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-foreground/[0.06]">
                <FileGlyph kind={fileKindOf(name)} />
            </span>
            <span className="min-w-0 truncate text-[13.5px] font-medium text-foreground">{name}</span>
        </a>
    );
}

const sentence = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
const words = (text: string) => text.replace(/_[0-9a-f]{8,}$/i, '').replace(/[_-]+/g, ' ').trim();

// ── connecting ──────────────────────────────────────────────────────────────

/** The apps an agent can use as tools: the integrations the platform API lists that have operations. */
export function useV1ToolApps(): ToolApp[] {
    const client = useWorkClient();
    const read = useV1('work:integrations:apps', () => Connection.integrations(undefined, { client, kind: 'app' }), { client });
    return useMemo(
        () =>
            (read.data ?? [])
                .filter((i) => (i.operationCount ?? 0) > 0)
                .map((i): ToolApp => ({ value: `automation-${i.name.replace(/_/g, '-')}`, label: i.label ?? sentence(words(i.name)), acceptedCredentialTypes: i.credentialTypes })),
        [read.data]
    );
}

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
 *  new tab; resolves with the connection once an account lands there. */
async function connectByLink(client: NoClick, integration: string, credentialType?: string): Promise<Connection> {
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
export function AppConnectLink({ app, name, onConnected, onClose }: ComponentProps<AppConnecting['Connect']>) {
    const client = useWorkClient();
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
export function ModelConnectLink({ credentialType, integration, title, description, others, onOpenChange, onConnected }: ModelConnectProps) {
    const client = useWorkClient();
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

const NO_SIGN_IN: ToolServerSignIn = {
    discover: async () => undefined,
    connect: async () => undefined,
    discoveryResult: null,
    isDiscovering: false,
    isConnecting: false,
    error: 'It asks you to sign in, which is done on NoClick: add it there, or give it a key here.',
};

/** No sign-in here: a tool server that asks for one is added on NoClick, or given its key. */
export function useNoToolServerSignIn(): ToolServerSignIn {
    return NO_SIGN_IN;
}

/** Add funds on NoClick's own page, in a new tab. */
export function FundsOnNoClick({ isOpen, forModel, onOpenChange }: AddFundsProps) {
    // NoClick's own site, as the console Work is drawn in names it (a page outside one links to noclick.com).
    const site = useContext(ConsoleContext)?.site ?? NOCLICK_SITE;
    if (!isOpen) return null;
    return (
        <ShellDialog
            open
            onOpenChange={onOpenChange}
            title="Add funds"
            description={forModel ? `${forModel.name} needs $${forModel.needsUsd} of funds you add before it runs on NoClick’s key.` : 'Funds are added on NoClick.'}
            footer={
                <>
                    <button type="button" onClick={() => onOpenChange(false)} className={BUTTON_GHOST}>
                        Close
                    </button>
                    <a href={addFundsUrl(site)} target="_blank" rel="noreferrer" onClick={() => onOpenChange(false)} className={cn(BUTTON_PRIMARY, 'inline-flex items-center gap-1.5')}>
                        <ExternalLink className="h-4 w-4" />
                        Add funds on NoClick
                    </a>
                </>
            }
        />
    );
}

// ── files ───────────────────────────────────────────────────────────────────

const MAX_TEXT_PREVIEW_BYTES = 512 * 1024;

function TextAt({ url, markdown }: { url: string; markdown: boolean }) {
    const [content, setContent] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    useEffect(() => {
        const controller = new AbortController();
        setContent(null);
        setError(null);
        fetch(url, { signal: controller.signal })
            .then(async (res) => {
                if (!res.ok) throw new Error(`Failed to load file (${res.status})`);
                setContent(await res.text());
            })
            .catch((e: unknown) => {
                if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Failed to load file');
            });
        return () => controller.abort();
    }, [url]);
    if (error) return <p className="m-0 py-4 text-[13px] text-red-600 dark:text-red-400">{error}</p>;
    if (content === null) return <p className="m-0 py-4 text-[13px] text-foreground/60 dark:text-foreground/40">Loading…</p>;
    if (markdown) return <StandardMarkdown content={content} className="text-[14px]" />;
    return <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-lg bg-muted/50 p-3 text-xs leading-relaxed text-foreground/90">{content}</pre>;
}

/** A workspace file at the link the platform API signed for it. */
function SignedFile({ file }: { file: FileEntry }) {
    if (!file.url) return <p className="m-0 py-4 text-[13px] text-foreground/60 dark:text-foreground/40">This file has no signed link yet: open its files again to refresh it.</p>;
    const ext = file.path.includes('.') ? file.path.slice(file.path.lastIndexOf('.') + 1).toLowerCase() : '';
    if (file.kind === 'image') return <img src={file.url} alt={file.path} className="max-h-[65vh] max-w-full rounded-lg object-contain" />;
    // An agent's own recording has no captions to give.
    // eslint-disable-next-line jsx-a11y/media-has-caption
    if (file.kind === 'video') return <video src={file.url} controls playsInline className="max-h-[65vh] w-full rounded-lg bg-black" />;
    // eslint-disable-next-line jsx-a11y/media-has-caption
    if (file.kind === 'audio') return <audio src={file.url} controls className="w-full py-6" />;
    const textLike = file.kind === 'doc' || file.kind === 'code' || file.kind === 'data' || ext === 'log';
    if (textLike && file.size <= MAX_TEXT_PREVIEW_BYTES && ext !== 'pdf') return <TextAt url={file.url} markdown={ext === 'md'} />;
    return (
        <p className="m-0 flex items-center gap-2 py-4 text-[13px] text-foreground/60 dark:text-foreground/40">
            <FileText className="h-4 w-4" /> No preview for this file{file.size > MAX_TEXT_PREVIEW_BYTES ? ' (too large)' : ' type'}: use Download.
        </p>
    );
}

export const workspacePreviewParts: PreviewParts = {
    Body: SignedFile,
    href: (file, _source, download) => (file.url ? (download ? `${file.url}&dl=1` : file.url) : undefined),
};

// ── where Work is ──────────────────────────────────────────────────────────

/** Work at `path` in this app: links to it, and going there loads it. */
export function workAddress(path: string): WorkAddress {
    return {
        href: (place) => `${path}?${place}`,
        go: (place) => window.location.assign(`${path}?${place}`),
    };
}
