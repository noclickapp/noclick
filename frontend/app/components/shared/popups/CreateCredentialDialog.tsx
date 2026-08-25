/**
 * CreateCredentialDialog lets users create or connect a credential without being
 * inside a workflow node. The user picks a service, then the fully self-contained
 * NodeCredentials UI (driven purely by a node type) handles the OAuth connect /
 * API-key form / QR flow exactly as it does inside a node — so there is zero
 * duplicated credential-creation logic. GlobalCreateCredentialDialog mounts one
 * instance in the dashboard shell that opens on the `noclick:create-credential`
 * event, so the command palette and the Credentials settings page open the same
 * flow from any screen.
 */

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { ChevronLeft, Search } from 'lucide-react';
import { toast } from 'sonner';
import { Dialog, DialogContent, DialogTitle } from '~/components/ui/dialog';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { NodeCredentials, hasCustomCredentialForm } from '~/components/workflow/NodeCredentials';
import { useServiceCredentialOptions } from '~/hooks/useServiceCredentialOptions';
import { useListKeyboardNav } from '~/hooks/useListKeyboardNav';
import { invalidateCredentialsCache } from '~/utils/credentialAutoSelect';
import { scoreFields } from '~/lib/fuzzyRank';
import { isTextEntryTarget } from '~/lib/keyboard';
import { openCommandPaletteScoped } from '~/lib/shortcuts';
import { cn } from '~/lib/utils';
import type { ServiceCredentialOption } from '~/utils/credentialTypes';

/** Dispatched to open the global create-credential dialog from any screen. */
export const CREATE_CREDENTIAL_EVENT = 'noclick:create-credential';
/** Dispatched after a credential is created so credential lists can refresh. */
export const CREDENTIALS_CHANGED_EVENT = 'noclick:credentials-changed';

/** Detail for opening the dialog pre-scoped to a service / existing credential. */
export interface OpenCredentialDetail {
    /** Credential type of an existing credential — preselects its service. */
    credentialType?: string;
    /** Existing credential id — preselects it within the service's form. */
    credentialId?: string;
}

/** Open the global create-credential dialog from any screen. Pass a detail to
 * open it straight to an existing credential (preselected). */
export function openCreateCredential(detail?: OpenCredentialDetail): void {
    window.dispatchEvent(
        new CustomEvent<OpenCredentialDetail>(CREATE_CREDENTIAL_EVENT, { detail })
    );
}

interface CreateCredentialDialogProps {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
    /** Called once a credential is created/connected so callers can refresh lists. */
    onCreated?: () => void;
    /** Preselect the service for this credential type (skips the picker). */
    initialCredentialType?: string;
    /** Preselect this existing credential within the service's form. */
    initialCredentialId?: string;
}

// Render the service's brand icon in its brand color — the same Icon + iconColor
// the canvas uses (resolved by node type), via the shared BrandIcon rule, so
// monochrome marks (BlueSky, HTTP, Twilio) keep their colour instead of being
// forced white. Colored brand SVGs ignore the text color and render as-is.
function ServiceIcon({ option }: { option: ServiceCredentialOption }) {
    return (
        <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-foreground/[0.06] flex-shrink-0">
            <BrandIcon Icon={option.Icon} iconColor={option.iconColor} className="w-5 h-5" />
        </div>
    );
}

export function CreateCredentialDialog({ isOpen, onOpenChange, onCreated, initialCredentialType, initialCredentialId }: CreateCredentialDialogProps) {
    const allServices = useServiceCredentialOptions();
    // Exclude services whose credentials need node context (agent model, MCP URL).
    const services = useMemo(
        () => allServices.filter((s) => !hasCustomCredentialForm(s.value)),
        [allServices],
    );
    const [selected, setSelected] = useState<ServiceCredentialOption | null>(null);
    const [search, setSearch] = useState('');
    // NodeCredentials reports the selected/created credential id back through here.
    const [credentialIds, setCredentialIds] = useState<Record<string, string>>({});
    // True when the form was reached by drilling in from the picker (vs. jumping
    // straight to it via the palette's "Open credential…"). Drives where Backspace
    // goes back to: the picker, or the palette.
    const [cameFromPicker, setCameFromPicker] = useState(false);
    // Enter the form for a picked service (picker → form).
    const selectService = (svc: ServiceCredentialOption) => {
        setSelected(svc);
        setCameFromPicker(true);
    };
    const searchInputRef = useRef<HTMLInputElement>(null);
    const listRef = useRef<HTMLDivElement>(null);
    // One-shot guard so the preselect applies once per open (and the user can
    // still hit "back" to the picker without it re-selecting).
    const appliedPreselectRef = useRef(false);

    // Reset for a fresh open — done on OPEN (not close) and in a layout effect so
    // the current view never flashes back to the service picker during the close
    // animation, nor shows stale state before the next open paints.
    useLayoutEffect(() => {
        if (isOpen) {
            setSelected(null);
            setSearch('');
            setCredentialIds({});
            setCameFromPicker(false);
            appliedPreselectRef.current = false;
        }
    }, [isOpen]);

    // Opened against an existing credential ("Open credential…"): jump straight to
    // its service form with that credential preselected. Layout effect (runs after
    // the reset above) so it applies before paint once the lazily loaded service
    // list is available.
    useLayoutEffect(() => {
        if (!isOpen || appliedPreselectRef.current || !initialCredentialType) return;
        if (services.length === 0) return;
        const svc = services.find((s) =>
            s.acceptedCredentialTypes.includes(initialCredentialType)
        );
        if (!svc) return;
        appliedPreselectRef.current = true;
        setSelected(svc);
        if (initialCredentialId) {
            setCredentialIds({ [initialCredentialType]: initialCredentialId });
        }
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

    // ↑/↓ move the highlight (wrapping at both ends), Enter picks the service,
    // Esc closes. Only active on the picker step.
    const {
        index: highlighted,
        setIndex: setHighlighted,
        handleKeyDown,
    } = useListKeyboardNav({
        count: filtered.length,
        active: isOpen && !selected,
        wrap: true,
        onSelect: (i) => {
            const svc = filtered[i];
            if (svc) selectService(svc);
        },
        onEscape: () => onOpenChange(false),
    });

    // Reset the highlight to the top whenever the query or step changes.
    useEffect(() => {
        setHighlighted(0);
    }, [search, selected, isOpen, setHighlighted]);

    // Keep the highlighted row scrolled into view while arrowing through.
    useEffect(() => {
        if (selected) return;
        const el = listRef.current?.querySelector<HTMLElement>(`[data-row-index="${highlighted}"]`);
        el?.scrollIntoView({ block: 'nearest' });
    }, [highlighted, selected]);

    // Backspace from the form steps back to where we came from: the service picker
    // (if we drilled in from it) or the palette's credential search (if we jumped
    // straight here via "Open credential…"). Uses a document listener — not the
    // content's onKeyDown — so it works even when focus sits on <body> (which is
    // the case for a preselected open, since the form has no element to autofocus).
    // Ignored while typing so credential fields keep their normal Backspace.
    useEffect(() => {
        if (!isOpen || !selected) return;
        const onKeyDown = (e: KeyboardEvent) => {
            if (e.key !== 'Backspace' || e.metaKey || e.ctrlKey || e.altKey) return;
            if (isTextEntryTarget(e.target)) return;
            e.preventDefault();
            if (cameFromPicker) {
                setSelected(null);
                setCredentialIds({});
            } else {
                onOpenChange(false);
                openCommandPaletteScoped('Credentials');
            }
        };
        document.addEventListener('keydown', onKeyDown);
        return () => document.removeEventListener('keydown', onKeyDown);
    }, [isOpen, selected, cameFromPicker, onOpenChange]);

    // Keep the search box focused on the picker step — on open and when returning
    // from a service form — so you can keep typing without re-clicking it.
    useEffect(() => {
        if (isOpen && !selected) searchInputRef.current?.focus();
    }, [isOpen, selected]);

    const handleCredentialChange = (next: Record<string, string>) => {
        // A credential type whose id newly appears/changes to a non-empty value
        // means a credential was just created/connected for it.
        const createdType = Object.keys(next).find(
            (type) => next[type]?.trim() && credentialIds[type] !== next[type],
        );
        setCredentialIds(next);
        if (createdType) {
            invalidateCredentialsCache();
            onCreated?.();
            toast.success(selected ? `${selected.label} credential added` : 'Credential added');
            // Close on success — the toast confirms it and returns the user to
            // wherever they opened the dialog from (e.g. the refreshed list).
            onOpenChange(false);
        }
    };

    return (
        <Dialog open={isOpen} onOpenChange={onOpenChange}>
            <DialogContent
                data-testid="create-credential-dialog"
                aria-describedby={undefined}
                // No enter/exit animation — this dialog is navigated to/from the
                // command palette ("Open credential…"), so it should feel instant.
                noAnimation
                onOpenAutoFocus={(e) => {
                    // Focus the search box rather than the first service row.
                    e.preventDefault();
                    searchInputRef.current?.focus();
                }}
                // Handle ↑/↓/Enter/Esc at the content level (not just the input) so
                // keyboard nav keeps working even when focus moves off the input
                // (e.g. Radix parks focus on the content, or after a click/scroll).
                onKeyDown={handleKeyDown}
                className="max-w-lg p-0 gap-0 overflow-hidden focus:outline-none focus-visible:outline-none"
            >
                {selected ? (
                    <div className="flex flex-col max-h-[80vh]">
                        {/* Header with back-to-picker control */}
                        <div className="flex items-center gap-2.5 px-4 py-3 border-b border-border dark:border-white/[0.06] pr-12">
                            <button
                                type="button"
                                onClick={() => {
                                    setSelected(null);
                                    setCredentialIds({});
                                }}
                                className="flex items-center justify-center h-7 w-7 -ml-1 rounded-md text-muted-foreground dark:text-white/40 hover:text-foreground hover:bg-foreground/[0.06] transition-colors flex-shrink-0"
                                title="Back to services"
                            >
                                <ChevronLeft className="h-4 w-4" />
                            </button>
                            <ServiceIcon option={selected} />
                            <DialogTitle className="text-base font-semibold text-foreground truncate">
                                Connect {selected.label}
                            </DialogTitle>
                        </div>
                        {/* NodeCredentials caps its rows/buttons at max-w-md (right for a
                            wide node panel, but it leaves a gap in this narrower dialog).
                            Neutralise that cap for descendants so buttons fill the width.
                            Nested popups (delete/share/upgrade) portal out, so they're
                            unaffected. */}
                        <div className="p-4 overflow-y-auto scrollbar-subtle [&_.max-w-md]:max-w-none">
                            <NodeCredentials
                                nodeType={selected.value}
                                nodeData={{}}
                                credentialIds={credentialIds}
                                onChange={handleCredentialChange}
                            />
                        </div>
                    </div>
                ) : (
                    <div className="flex flex-col max-h-[80vh]">
                        <div className="px-4 pt-4 pb-3">
                            <DialogTitle className="text-lg font-semibold text-foreground tracking-tight">
                                Add a credential
                            </DialogTitle>
                            <p className="text-sm text-muted-foreground dark:text-white/40 mt-1">
                                Connect a service to use across your workflows.
                            </p>
                        </div>

                        {/* Service search. The icon wrapper is `relative` around the input
                            ONLY (padding lives on the outer div) so the icon centres on the
                            input height — the prior version centred it on a padded box, which
                            pushed it low. Matches the Credentials settings search pattern. */}
                        <div className="px-4 pb-3">
                            <div className="relative">
                                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground dark:text-white/30" />
                                <input
                                    ref={searchInputRef}
                                    type="text"
                                    placeholder="Search services..."
                                    value={search}
                                    onChange={(e) => setSearch(e.target.value)}
                                    className="w-full pl-9 pr-3 py-2 text-sm bg-foreground/[0.04] border border-input dark:border-white/[0.08] rounded-lg text-foreground placeholder:text-[hsl(var(--placeholder))] outline-none focus:border-foreground/20 transition-colors"
                                />
                            </div>
                        </div>

                        {/* Service list */}
                        <div ref={listRef} className="px-2 pb-3 overflow-y-auto scrollbar-subtle max-h-[52vh]">
                            {services.length === 0 ? (
                                <div className="py-12 text-center text-sm text-muted-foreground dark:text-white/40">Loading services…</div>
                            ) : filtered.length === 0 ? (
                                <div className="py-12 text-center text-sm text-muted-foreground dark:text-white/40">
                                    No services matching &ldquo;{search}&rdquo;
                                </div>
                            ) : (
                                filtered.map((svc, i) => (
                                    <button
                                        key={svc.value}
                                        type="button"
                                        data-testid="credential-service-row"
                                        data-row-index={i}
                                        onMouseMove={() => setHighlighted(i)}
                                        onClick={() => selectService(svc)}
                                        className={cn(
                                            'w-full flex items-center gap-3 px-2 py-2 rounded-lg text-left transition-colors',
                                            i === highlighted ? 'bg-foreground/[0.06]' : 'hover:bg-foreground/[0.05]',
                                        )}
                                    >
                                        <ServiceIcon option={svc} />
                                        <span className="flex-1 truncate text-[0.9375rem] text-foreground/90">{svc.label}</span>
                                    </button>
                                ))
                            )}
                        </div>
                    </div>
                )}
            </DialogContent>
        </Dialog>
    );
}

/**
 * Global mount point: opens the dialog on the `noclick:create-credential` event
 * (dispatched by the command palette and the Credentials settings page) and
 * broadcasts `noclick:credentials-changed` when a credential is created so any
 * open credential list refreshes. Mounted once in the dashboard shell.
 */
export function GlobalCreateCredentialDialog() {
    const [open, setOpen] = useState(false);
    const [preselect, setPreselect] = useState<OpenCredentialDetail>({});

    useEffect(() => {
        const onOpen = (e: Event) => {
            setPreselect((e as CustomEvent<OpenCredentialDetail>).detail ?? {});
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
