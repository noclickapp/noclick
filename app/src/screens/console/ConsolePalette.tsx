// ⌘K: every section, the objects opened recently, and "Go to" for a pasted
// value, resolved server-side in one GET /v1/objects/{ref} (never a probe per type). Only the account's signed-in
// owner can make that lookup (ownerOnly.ts), so a console acting as a key has no "Go to".
import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { ArrowRight, History, Plus, Search } from 'lucide-react';
import { useNavigate } from 'react-router';
import { cn } from '@/ui/utils';
import { LogoMark } from '@/ui/LogoMark';
import { NotFound } from 'noclick';
import { resolveObject, type ObjectRef, type ObjectType } from '@/sdk/owner';
import { isUuid, truncateId } from '@/screens/console/lib/format';
import { legacyKeysUrl } from '@/screens/console/lib/site';
import { userPath } from '@/screens/console/lib/userFilter';
import { consoleHref, useConsole } from '@/screens/console/hooks/useConsole';
import { useRecent } from '@/screens/console/hooks/useRecent';
import { OVERLAY } from './ui/ConsoleDialog';
import { READABLE_PLACEHOLDERS } from './ui/tokens';
import { useOwnerOnly } from './ownerOnly';
import { destinations } from './sections';

export const OPEN_CONSOLE_PALETTE = 'noclick:developers-palette';

export function openConsolePalette(): void {
    window.dispatchEvent(new Event(OPEN_CONSOLE_PALETTE));
}

export const OBJECT_LABELS: Record<ObjectType, string> = {
    operation: 'Operation',
    agent: 'Agent',
    user: 'User',
    human_request: 'Human request',
    connection: 'Connection',
    credential: 'Credential',
    channel: 'Channel',
    inbox: 'Inbox',
    sandbox: 'Sandbox',
    phone_number: 'Phone number',
    workspace: 'Workspace',
    webhook: 'Webhook',
    secret: 'Secret',
    dict: 'Dict',
    queue: 'Queue',
    volume: 'Volume',
    bucket: 'Bucket',
    mcp_server: 'MCP server',
    key: 'Key',
    legacy_key: 'Workflow SDK key',
};

/** Where a resolved object opens; null when no console page lists it. `site` is NoClick's own (`ConsoleContextValue.site`). */
export function objectHref(basePath: string, ref: ObjectRef, site = ''): string | null {
    const at = (path: string, params?: Record<string, string>) => consoleHref(basePath, path, params);
    switch (ref.type) {
        case 'operation':
            return at('logs', { op: ref.id });
        case 'agent':
            return at(`agents/${ref.id}`);
        case 'user':
            return at(userPath(ref.id));
        case 'human_request':
            return at('logs', { req: ref.id });
        case 'connection':
        case 'credential':
            // A credential is what a connection holds (Logs shows its id): its user's page lists that user's, Resources the account's.
            return ref.user_id ? at(userPath(ref.user_id)) : at('resources/connections');
        case 'channel':
            return at('resources/channels', { channel: ref.id });
        case 'inbox':
            return at('resources/inboxes', { inbox: ref.id });
        case 'sandbox':
            return at('resources/sandboxes', { sandbox: ref.id });
        case 'phone_number':
            return at('resources/phone', { number: ref.id });
        case 'workspace':
            return at('resources/channels', { workspace: ref.id });
        case 'webhook':
            return at('settings/webhooks', { webhook: ref.id });
        case 'secret':
            return at('resources/secrets', { secret: ref.id });
        case 'dict':
            return at('resources/dicts', { dict: ref.id });
        case 'queue':
            return at('resources/queues', { queue: ref.id });
        case 'volume':
            return at('resources/volumes', { volume: ref.id });
        case 'bucket':
            return at('resources/storage', { bucket: ref.id });
        case 'mcp_server':
            return at('', { mcp: ref.id });
        case 'key':
            return at('keys', { key: ref.id });
        case 'legacy_key':
            return legacyKeysUrl(site);
    }
}

/** A value that names an object rather than a section. */
export function looksLikeRef(value: string): boolean {
    const v = value.trim();
    return isUuid(v) || v.startsWith('nk_');
}

type Lookup = { state: 'idle' } | { state: 'loading'; value: string } | { state: 'found'; value: string; ref: ObjectRef } | { state: 'missing'; value: string } | { state: 'error'; value: string; message: string };

interface Item {
    id: string;
    group: 'Go to' | 'Actions' | 'Navigation' | 'Recent';
    label: ReactNode;
    hint?: string;
    href: string | null;
    icon: ReactNode;
}

export function ConsolePalette() {
    const { client, basePath, lab, site, home } = useConsole();
    const ownerCan = useOwnerOnly();
    const lookedUp = ownerCan('objectLookup');
    const navigate = useNavigate();
    const recent = useRecent();
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState('');
    const [active, setActive] = useState(0);
    const [lookup, setLookup] = useState<Lookup>({ state: 'idle' });
    const listRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                setOpen((o) => !o);
            }
        };
        const onOpen = () => setOpen(true);
        window.addEventListener('keydown', onKey);
        window.addEventListener(OPEN_CONSOLE_PALETTE, onOpen);
        return () => {
            window.removeEventListener('keydown', onKey);
            window.removeEventListener(OPEN_CONSOLE_PALETTE, onOpen);
        };
    }, []);

    const needle = query.trim().toLowerCase();
    const nav = useMemo(
        () =>
            destinations(lab, { can: ownerCan })
                .filter((d) => !needle || d.label.toLowerCase().includes(needle) || d.id.includes(needle))
                .map<Item>((d) => {
                    const Icon = d.icon;
                    return { id: `nav:${d.id}`, group: 'Navigation', label: d.label, href: consoleHref(basePath, d.path), icon: <Icon className="h-4 w-4" /> };
                }),
        [needle, basePath, lab, ownerCan]
    );
    const recents = useMemo(
        () =>
            recent
                .filter((r) => !needle || r.label.toLowerCase().includes(needle) || r.id.toLowerCase().includes(needle))
                .map<Item>((r) => ({
                    id: `recent:${r.type}:${r.id}`,
                    group: 'Recent',
                    label: r.label,
                    hint: OBJECT_LABELS[r.type as ObjectType] ?? r.type,
                    href: consoleHref(basePath, r.path, r.params),
                    icon: <History className="h-4 w-4" />,
                })),
        [recent, needle, basePath]
    );

    // Resolve a pasted id / key prefix / user id, or free text nothing else matched.
    const shouldResolve = lookedUp && !!needle && (looksLikeRef(query) || (needle.length >= 3 && !nav.length && !recents.length));
    useEffect(() => {
        if (!shouldResolve) {
            setLookup({ state: 'idle' });
            return;
        }
        const value = query.trim();
        const controller = new AbortController();
        setLookup({ state: 'loading', value });
        const timer = window.setTimeout(async () => {
            try {
                const ref = await resolveObject(client, value, controller.signal);
                if (!controller.signal.aborted) setLookup({ state: 'found', value, ref });
            } catch (err) {
                if (controller.signal.aborted) return;
                if (err instanceof NotFound) setLookup({ state: 'missing', value });
                else setLookup({ state: 'error', value, message: err instanceof Error ? err.message : String(err) });
            }
        }, 250);
        return () => {
            controller.abort();
            window.clearTimeout(timer);
        };
    }, [shouldResolve, query, client]);

    const goto: Item[] =
        lookup.state === 'found'
            ? [
                  {
                      id: 'goto',
                      group: 'Go to',
                      label:
                          lookup.ref.type === 'legacy_key' ? (
                              <span>This is a workflow SDK key → Settings → Developer</span>
                          ) : (
                              <span>
                                  Go to <strong className="font-semibold">{OBJECT_LABELS[lookup.ref.type]}</strong> — <span className="font-mono text-[12px]">{lookup.ref.type === 'user' ? lookup.ref.id : truncateId(lookup.ref.id)}</span>
                              </span>
                          ),
                      href: objectHref(basePath, lookup.ref, site),
                      icon: <ArrowRight className="h-4 w-4" />,
                  },
              ]
            : [];
    // "New agent" shows the code that makes one (`?new=agent` on Home), as Home's button does.
    const actions: Item[] = !needle || 'new agent'.includes(needle) || needle.startsWith('new') || needle.startsWith('create')
        ? [{ id: 'action:new-agent', group: 'Actions', label: 'New agent', hint: 'Code', href: consoleHref(basePath, '', { new: 'agent' }), icon: <Plus className="h-4 w-4" /> }]
        : [];
    // The way back to the app, as the account menu has it.
    const app: Item[] = !needle || 'noclick app'.includes(needle) || needle.startsWith('back')
        ? [{ id: 'nav:app', group: 'Navigation', label: 'NoClick app', href: home, icon: <LogoMark className="h-4 w-4 opacity-60" alt="" /> }]
        : [];
    const items = [...goto, ...actions, ...recents, ...nav, ...app];

    const run = (item: Item | undefined) => {
        if (!item?.href) return;
        setOpen(false);
        setQuery('');
        if (item.href.startsWith(basePath)) navigate(item.href);
        else window.location.assign(item.href);
    };

    const onKeyDown = (e: ReactKeyboardEvent) => {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            setActive((a) => Math.min(items.length - 1, a + 1));
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setActive((a) => Math.max(0, a - 1));
        } else if (e.key === 'Enter') {
            e.preventDefault();
            run(items[active]);
        }
    };

    let lastGroup = '';
    return (
        <Dialog.Root
            open={open}
            onOpenChange={(next) => {
                setOpen(next);
                if (!next) setQuery('');
            }}
        >
            <Dialog.Portal>
                <Dialog.Overlay className={OVERLAY} />
                <Dialog.Content
                    className={cn(
                        'fixed left-1/2 top-[12vh] z-[70] flex max-h-[70vh] w-[calc(100vw-32px)] max-w-[560px] -translate-x-1/2 flex-col overflow-hidden rounded-xl border border-border bg-popover text-popover-foreground shadow-2xl focus:outline-none',
                        READABLE_PLACEHOLDERS
                    )}
                >
                    <Dialog.Title className="sr-only">Search the developer console</Dialog.Title>
                    <Dialog.Description className="sr-only">{lookedUp ? 'Go to a section, a recent object, or paste an id.' : 'Go to a section or a recent object.'}</Dialog.Description>
                    <div className="flex items-center gap-2 border-b border-border px-3">
                        <Search className="h-4 w-4 text-muted-foreground" />
                        <input
                            value={query}
                            onChange={(e) => {
                                setQuery(e.target.value);
                                setActive(0);
                            }}
                            onKeyDown={onKeyDown}
                            placeholder={lookedUp ? 'Go to a section, or paste an id, key prefix or user id' : 'Go to a section'}
                            aria-label="Search"
                            className="h-11 w-full bg-transparent text-[14px] text-foreground outline-none placeholder:text-[hsl(var(--placeholder))]"
                        />
                    </div>
                    <div ref={listRef} role="listbox" className="min-h-0 flex-1 overflow-y-auto p-1.5">
                        {lookup.state === 'loading' && <p className="m-0 px-2 py-2 text-[13px] text-muted-foreground">Looking up {lookup.value}…</p>}
                        {lookup.state === 'missing' && <p className="m-0 px-2 py-2 text-[13px] text-muted-foreground">Nothing in this account is named {lookup.value}.</p>}
                        {lookup.state === 'error' && <p className="m-0 px-2 py-2 text-[13px] text-red-600 dark:text-red-400">{lookup.message}</p>}
                        {items.map((item, i) => {
                            const header = item.group !== lastGroup ? item.group : null;
                            lastGroup = item.group;
                            return (
                                <div key={item.id}>
                                    {header && <div className="px-2 pb-1 pt-2 text-[12px] font-medium text-muted-foreground">{header}</div>}
                                    <button
                                        type="button"
                                        role="option"
                                        aria-selected={i === active}
                                        aria-disabled={!item.href}
                                        onMouseMove={() => setActive(i)}
                                        onClick={() => run(item)}
                                        className={cn(
                                            'flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-[13px] text-foreground',
                                            i === active && 'bg-foreground/[0.06]',
                                            !item.href && 'cursor-default opacity-60'
                                        )}
                                    >
                                        <span className="text-muted-foreground">{item.icon}</span>
                                        <span className="min-w-0 flex-1 truncate">{item.label}</span>
                                        {item.hint && <span className="text-[12px] text-muted-foreground">{item.hint}</span>}
                                        {!item.href && <span className="text-[12px] text-muted-foreground">No page lists this yet</span>}
                                    </button>
                                </div>
                            );
                        })}
                    </div>
                </Dialog.Content>
            </Dialog.Portal>
        </Dialog.Root>
    );
}
