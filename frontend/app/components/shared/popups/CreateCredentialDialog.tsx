/**
 * The Connect dialog: the one popup that connects an app's account, opened from a Connections tile, the command
 * palette ("Connect an app…", "Open credential…") or a broken account's Reconnect. Without an app it lists them to
 * search; with one it is AppConnect (a switch between the ways in, a key as get-it-then-paste-it steps, the accounts
 * already connected, asking someone who can; ConnectAppStep) under a header that follows it to what connecting proved.
 * GlobalCreateCredentialDialog mounts one instance in the dashboard shell that opens on `noclick:create-credential`.
 */

import { lazy, Suspense, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Loader2, Plug, Search } from 'lucide-react';
import { ShellDialog } from '~/components/shell/ShellDialog';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { connectDialogHeader, type ConnectResult, type ConnectStage } from '~/components/credential/connect/connectHeader';
import { accountProblem } from '~/components/shell/connections/accounts';
import { hasCustomCredentialForm } from '~/components/workflow/customCredentialForms';
import { useServiceCredentialOptions } from '~/hooks/useServiceCredentialOptions';
import { useListKeyboardNav } from '~/hooks/useListKeyboardNav';
import { scoreFields } from '~/lib/fuzzyRank';
import { isTextEntryTarget } from '~/lib/keyboard';
import { navigateToAccount } from '~/lib/navigation';
import { openCommandPaletteScoped } from '~/lib/shortcuts';
import { cn } from '~/lib/utils';
import type { CredentialInfo } from '~/types/socket-events.generated';
import { getAllCredentialsFromCache, prefetchCredentials } from '~/utils/credentialAutoSelect';
import type { ServiceCredentialOption } from '~/utils/credentialTypes';

// The connect flow (and the node schemas it reads) loads with the dialog's first open, not with every page that
// mounts the dialog or reads its events.
const loadConnectStep = () => import('./ConnectAppStep');
const ConnectAppStep = lazy(loadConnectStep);

/** Dispatched to open the global create-credential dialog from any screen. */
export const CREATE_CREDENTIAL_EVENT = 'noclick:create-credential';
/** Dispatched after a credential is created so credential lists can refresh. */
export const CREDENTIALS_CHANGED_EVENT = 'noclick:credentials-changed';

/** Detail for opening the dialog pre-scoped to a service / existing credential. */
export interface OpenCredentialDetail {
    /** Credential type of an existing credential — preselects its service. */
    credentialType?: string;
    /** Existing credential id: a broken one is reconnected here (its way in opens first), a working one shows its page. */
    credentialId?: string;
    /** Reconnect `credentialId` even though nothing lists it as broken (a key its provider just turned down). */
    reconnect?: boolean;
}

/** Open the global create-credential dialog from any screen. Pass a detail to
 * open it straight to a service (or to reconnecting one of its accounts). */
export function openCreateCredential(detail?: OpenCredentialDetail): void {
    window.dispatchEvent(new CustomEvent<OpenCredentialDetail>(CREATE_CREDENTIAL_EVENT, { detail }));
}

interface CreateCredentialDialogProps {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
    /** Called once a credential is created/connected so callers can refresh lists. */
    onCreated?: () => void;
    /** Preselect the service for this credential type (skips the picker). */
    initialCredentialType?: string;
    /** The account being reconnected. */
    initialCredentialId?: string;
}

// The service's brand mark, as its Connections tile shows it.
function ServiceMark({ option, size = 'md' }: { option: ServiceCredentialOption; size?: 'sm' | 'md' }) {
    return <BrandIcon Icon={option.Icon} iconColor={option.iconColor} className={size === 'md' ? 'h-[22px] w-[22px]' : 'h-5 w-5'} />;
}

export function CreateCredentialDialog({ isOpen, onOpenChange, onCreated, initialCredentialType, initialCredentialId }: CreateCredentialDialogProps) {
    const allServices = useServiceCredentialOptions();
    // Exclude services whose credentials need node context (agent model, MCP URL).
    const services = useMemo(() => allServices.filter((s) => !hasCustomCredentialForm(s.value)), [allServices]);
    const [selected, setSelected] = useState<ServiceCredentialOption | null>(null);
    const [search, setSearch] = useState('');
    const [stage, setStage] = useState<ConnectStage>('connect');
    const [result, setResult] = useState<ConnectResult | undefined>();
    // Reached by drilling in from the picker (vs. jumping straight to a service): where Backspace goes back to.
    const [cameFromPicker, setCameFromPicker] = useState(false);
    const searchInputRef = useRef<HTMLInputElement>(null);
    const listRef = useRef<HTMLDivElement>(null);
    // One-shot guard so the preselect applies once per open (and the user can still go back to the picker).
    const appliedPreselectRef = useRef(false);

    // The account the dialog opened to reconnect, on the service it belongs to.
    const [reconnect, setReconnect] = useState<{ service: string; credentialId: string; credentialType: string } | undefined>();

    const selectService = (svc: ServiceCredentialOption) => {
        setSelected(svc);
        setStage('connect');
        setCameFromPicker(true);
    };

    // Reset for a fresh open, on OPEN (not close) and before paint, so the view never flashes back to the picker
    // during the close animation, nor shows stale state before the next open paints.
    useLayoutEffect(() => {
        if (isOpen) {
            void loadConnectStep();
            setSelected(null);
            setSearch('');
            setStage('connect');
            setResult(undefined);
            setCameFromPicker(false);
            setReconnect(undefined);
            appliedPreselectRef.current = false;
        }
    }, [isOpen]);

    // Opened on a service ("Connect" on a tile, "Open credential…", a Reconnect): straight to its connect flow, on
    // the reconnected account's way in. Runs once the lazily loaded service list is in.
    useLayoutEffect(() => {
        if (!isOpen || appliedPreselectRef.current || !initialCredentialType || services.length === 0) return;
        const svc = services.find((s) => s.acceptedCredentialTypes.includes(initialCredentialType));
        if (!svc) return;
        appliedPreselectRef.current = true;
        setSelected(svc);
        if (initialCredentialId) setReconnect({ service: svc.value, credentialId: initialCredentialId, credentialType: initialCredentialType });
    }, [isOpen, initialCredentialType, initialCredentialId, services]);

    const filtered = useMemo(() => {
        const q = search.trim();
        if (!q) return services;
        return services
            .map((s) => ({ s, score: scoreFields(q, [s.label, s.acceptedCredentialTypes.join(' ')]) }))
            .filter((x) => x.score !== null)
            .sort((a, b) => (a.score as number) - (b.score as number))
            .map((x) => x.s);
    }, [services, search]);

    // ↑/↓ move the highlight (wrapping at both ends), Enter picks the service, Esc closes. Only on the picker.
    const { index: highlighted, setIndex: setHighlighted, handleKeyDown } = useListKeyboardNav({
        count: filtered.length,
        active: isOpen && !selected,
        wrap: true,
        onSelect: (i) => {
            const svc = filtered[i];
            if (svc) selectService(svc);
        },
        onEscape: () => onOpenChange(false),
    });

    useEffect(() => {
        setHighlighted(0);
    }, [search, selected, isOpen, setHighlighted]);

    // The search keeps focus on the picker, on open and coming back from an app, so typing never needs a click.
    useEffect(() => {
        if (isOpen && !selected) searchInputRef.current?.focus();
    }, [isOpen, selected]);

    useEffect(() => {
        if (selected) return;
        listRef.current?.querySelector<HTMLElement>(`[data-row-index="${highlighted}"]`)?.scrollIntoView({ block: 'nearest' });
    }, [highlighted, selected]);

    // Backspace from the connect step goes back where it came from: the picker, or the palette's credential search.
    // A document listener, so it works when focus sits on <body>; ignored while typing.
    useEffect(() => {
        if (!isOpen || !selected) return;
        const onKeyDown = (e: KeyboardEvent) => {
            if (e.key !== 'Backspace' || e.metaKey || e.ctrlKey || e.altKey) return;
            if (isTextEntryTarget(e.target)) return;
            e.preventDefault();
            if (cameFromPicker) {
                setSelected(null);
            } else {
                onOpenChange(false);
                openCommandPaletteScoped('Credentials');
            }
        };
        document.addEventListener('keydown', onKeyDown);
        return () => document.removeEventListener('keydown', onKeyDown);
    }, [isOpen, selected, cameFromPicker, onOpenChange]);

    const header = selected
        ? connectDialogHeader(selected.label, stage, result)
        : { title: 'Connect an app', description: 'Search the apps NoClick works with.' };

    return (
        <ShellDialog
            open={isOpen}
            onOpenChange={onOpenChange}
            title={header.title}
            description={header.description}
            mark={selected ? <ServiceMark option={selected} /> : <Plug className="h-5 w-5" strokeWidth={1.75} />}
            // ↑/↓/Enter/Esc wherever focus sits on the list (Radix can park it on the dialog itself).
            onKeyDown={selected ? undefined : handleKeyDown}
            testId="create-credential-dialog"
        >
            {selected ? (
                <Suspense
                    fallback={
                        <div className="flex justify-center py-8">
                            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                        </div>
                    }
                >
                    <ConnectAppStep
                        key={selected.value}
                        service={selected}
                        reconnect={reconnect?.service === selected.value ? reconnect : undefined}
                        onChooseAnother={cameFromPicker ? () => setSelected(null) : undefined}
                        onStage={(next, landed) => {
                            setStage(next);
                            if (landed) setResult(landed);
                        }}
                        onConnected={() => onCreated?.()}
                        onClose={() => onOpenChange(false)}
                    />
                </Suspense>
            ) : (
                <div className="pb-4">
                    <label className="relative block">
                        <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                        <input
                            ref={searchInputRef}
                            type="search"
                            placeholder="Search apps"
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                            aria-label="Search apps"
                            className="h-10 w-full rounded-xl border border-border bg-transparent pl-10 pr-3.5 text-[14px] text-foreground outline-none transition-colors placeholder:text-[hsl(var(--placeholder))] focus:border-foreground/25 dark:border-foreground/[0.1]"
                        />
                    </label>
                    <div ref={listRef} className="-mx-2 mt-3 max-h-[52vh] overflow-y-auto px-2 scrollbar-subtle" role="listbox" aria-label="Apps">
                        {services.length === 0 ? (
                            <div className="py-12 text-center text-[13px] text-muted-foreground">Loading apps…</div>
                        ) : filtered.length === 0 ? (
                            <div className="py-12 text-center text-[13px] text-muted-foreground">Nothing matches “{search.trim()}”.</div>
                        ) : (
                            filtered.map((svc, i) => (
                                <button
                                    key={svc.value}
                                    type="button"
                                    role="option"
                                    aria-selected={i === highlighted}
                                    data-testid="credential-service-row"
                                    data-row-index={i}
                                    onMouseMove={() => setHighlighted(i)}
                                    onClick={() => selectService(svc)}
                                    className={cn('flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left transition-colors', i === highlighted ? 'bg-foreground/[0.06]' : 'hover:bg-foreground/[0.04]')}
                                >
                                    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[10px] bg-foreground/[0.05]">
                                        <ServiceMark option={svc} size="sm" />
                                    </span>
                                    <span className="flex-1 truncate text-[14px] text-foreground">{svc.label}</span>
                                </button>
                            ))
                        )}
                    </div>
                </div>
            )}
        </ShellDialog>
    );
}

/**
 * Global mount point: opens the dialog on the `noclick:create-credential` event
 * (dispatched by Connections, the command palette and the Credentials settings page) and
 * broadcasts `noclick:credentials-changed` when a credential is created so any
 * open credential list refreshes. Mounted once in the dashboard shell.
 */
export function GlobalCreateCredentialDialog() {
    const [open, setOpen] = useState(false);
    const [preselect, setPreselect] = useState<OpenCredentialDetail>({});

    useEffect(() => {
        const onOpen = async (e: Event) => {
            const detail = (e as CustomEvent<OpenCredentialDetail>).detail ?? {};
            // Opening an account that works shows the account (the palette, a resource's Manage); a broken one, or one
            // asked to reconnect, opens here on its way back in.
            if (detail.credentialId && !detail.reconnect) {
                const find = () => (getAllCredentialsFromCache() as CredentialInfo[]).find((c) => c.id === detail.credentialId);
                if (!find()) await prefetchCredentials();
                const credential = find();
                if (credential && !accountProblem(credential)) {
                    navigateToAccount(credential.id);
                    return;
                }
            }
            setPreselect(detail);
            setOpen(true);
        };
        window.addEventListener(CREATE_CREDENTIAL_EVENT, onOpen);
        return () => window.removeEventListener(CREATE_CREDENTIAL_EVENT, onOpen);
    }, []);

    return (
        <CreateCredentialDialog
            isOpen={open}
            onOpenChange={(o) => {
                setOpen(o);
                if (!o) setPreselect({});
            }}
            initialCredentialType={preselect.credentialType}
            initialCredentialId={preselect.credentialId}
            onCreated={() => window.dispatchEvent(new CustomEvent(CREDENTIALS_CHANGED_EVENT))}
        />
    );
}
