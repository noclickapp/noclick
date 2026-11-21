// A step's accounts: which of your accounts it runs as (a picker per way in that has any), what connecting it proved,
// why one can't be used, and connecting another in place. Whoever renders the form says how through the canvas's
// slots: the ways in and the accounts they list, saving a choice, sharing and deleting one, and a type's own account
// form (`canvas.step.accounts`); connecting an app's account goes through `connect.app` and an AI account through
// `connect.model`, the only ways to.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, ChevronDown, Edit2, Info, Plus, Search, Share2, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { useClient, useProvidedClient } from '@/sdk/client';
import { methodFromRequirement, type CredentialRequirement } from '@/lib/accountWays';
import type { ConnectionCheck } from '@/lib/connectionCheck';
import { methodName, copyMethodOf } from '@/lib/credentialCopy';
import { kindFromCredentialType } from '@/lib/credentialMethodKind';
import { fuzzyFilter } from '@/lib/fuzzySearch';
import { useSlot } from '@/slots';
import { INLINE_ACTION } from '@/ui/buttons';
import { ConnectionVerdict, StoredVerdict } from '@/ui/ConnectionVerdict';
import { DeleteConfirmPopup } from '@/ui/DeleteConfirmPopup';
import { FIELD_LABEL } from '@/ui/fields';
import { CONNECT_APP, CONNECT_MODEL, type LandedAccount } from '@/ui/slots';
import { cn } from '@/ui/utils';
import { STEP_ACCOUNTS, type AccountWaysRead, type StepAccount } from '../slots';

/** What a just-chosen account is called, so others looking at the step name it at once: never a secret. */
export interface AccountMeta {
    id: string;
    name: string;
    credential_type: string;
}

/** A variable of the workflow's that holds an account, offered beside the accounts of its types. */
export interface CredentialVariableChoice {
    name: string;
    label: string;
    credentialTypes: string[];
}

export interface NodeCredentialsProps {
    nodeType: string;
    /** The step's operation and settings (`config` holds them nested). */
    nodeData?: Record<string, any>;
    /** Its accounts: credential type → the account's id. */
    credentialIds?: Record<string, string>;
    /** Its accounts as chosen here, with what each just-chosen one is called (`credentialMeta`) and which were just
     *  deleted (`credentialRemoved`), so others looking at the step follow at once. */
    onChange?: (credentialIds: Record<string, string>, credentialMeta?: Record<string, AccountMeta>, credentialRemoved?: string[]) => void;
    credentialVariables?: CredentialVariableChoice[];
    /** A compact host (a question someone was asked, a setup step): no labels where the host has its own, no asking
     *  someone else, picking and connecting only. */
    compact?: boolean;
    /** What connecting proved about an account just connected or re-keyed here (null: nothing could be judged). */
    onVerification?: (credentialId: string, verification: ConnectionCheck | null) => void;
    /** Hears an account the person just connected here (a sign-in, a key, a scan, a purchase), never one picked from
     *  the list. */
    onConnected?: (credentialId: string) => void;
}

// Owner-only actions (Update, Share, Delete) show only on an account the person owns: refused from anyone else.
const isOwnedByViewer = (cred: StepAccount): boolean => cred.access_type === 'owner' || cred.owned_by_me === true;

const ownerLabel = (cred: StepAccount): string => cred.owner_name || cred.shared_by_name || cred.shared_by_email || 'another user';

const isQRScan = (credentialSchema: Record<string, unknown> | undefined): boolean => kindFromCredentialType(credentialSchema?.['x-credential-type'] as string | undefined) === 'qr_scan';

// A notice shown above the ways in (an integration pending approval, or unavailable).
const noticeOf = (credentialSchema: Record<string, unknown> | undefined): string | undefined => credentialSchema?.['x-credential-notice'] as string | undefined;

/** Dead but recoverable: the provider's session dropped (connecting the same account again fixes it), unlike
 *  `revoked_at`, a disconnect for good. */
const isDisconnected = (cred: StepAccount) => cred.connection_healthy === false;

/** Healthy first, then disconnected, then revoked. */
const deadRank = (cred: StepAccount) => (cred.revoked_at ? 2 : isDisconnected(cred) ? 1 : 0);

/** The step's account pickers, drawn once its ways in have been read (until then, nothing: never "needs no account"). */
export function NodeCredentials(props: NodeCredentialsProps) {
    const host = useSlot(STEP_ACCOUNTS);
    const ways = host.useWays(props.nodeType, props.nodeData ?? NO_SETTINGS);
    return ways.status === 'loading' ? null : <NodeCredentialsForm {...props} ways={ways} />;
}

const NO_SETTINGS: Record<string, any> = {};

function NodeCredentialsForm({ nodeType, nodeData = NO_SETTINGS, credentialIds = {}, onChange, credentialVariables, compact, onVerification, onConnected, ways }: NodeCredentialsProps & { ways: Exclude<AccountWaysRead, { status: 'loading' }> }) {
    const host = useSlot(STEP_ACCOUNTS);
    const connecting_ = useSlot(CONNECT_APP);
    const client = useProvidedClient();
    const save = host.useSave();
    const remove = host.useRemove();
    const requiredCredentials = useMemo(() => (ways.status === 'ready' ? ways.ways : []), [ways]);
    const usageBasedBillingAvailable = ways.status === 'ready' && ways.optional;
    const app = ways.status === 'ready' ? ways.app : '';
    const CustomCredentialForm = host.forms[nodeType];

    // Ref to track required credentials for selection cleanup
    const requiredCredentialsRef = useRef<CredentialRequirement[]>([]);
    useEffect(() => {
        requiredCredentialsRef.current = requiredCredentials;
    }, [requiredCredentials]);

    // The resolved list, so a selection can carry the chosen account's name.
    const availableCredentialsRef = useRef<StepAccount[]>([]);
    // Accounts connected from this panel (a sign-in, a key, a bought number, a scanned QR): selected before the
    // refreshed list holds them, so the missing-account warning must not judge them by the stale list.
    const mintedCredentialIdsRef = useRef<Set<string>>(new Set());

    /** Tells the step's host, then saves it where the host doesn't, saying why when it couldn't. */
    const changed = useCallback(
        (next: Record<string, string>, meta?: Record<string, AccountMeta>, removed?: string[], saving?: { credentialType: string; credentialId: string | null }) => {
            onChange?.(next, meta, removed);
            if (save && saving) {
                save(saving.credentialType, saving.credentialId).catch((error: unknown) =>
                    toast.error('The step’s account couldn’t be saved', { description: error instanceof Error ? error.message : String(error) })
                );
            }
        },
        [onChange, save]
    );

    // A custom form's choices (where the type's own form picks its accounts).
    const handleCredentialIdsChange = useCallback((newCredentialIds: Record<string, string>) => {
        onChange?.(newCredentialIds);
    }, [onChange]);

    const handleCredentialSelect = useCallback(
        (credentialType: string, credentialId: string, knownCredential?: LandedAccount) => {
            // Only keys that are current credential types: a stale key from an older schema would shadow the right one.
            const validTypes = new Set(requiredCredentialsRef.current.map((r) => r.credential_type));
            const cleaned: Record<string, string> = {};
            for (const [k, v] of Object.entries(credentialIds)) {
                if (validTypes.has(k)) cleaned[k] = v;
            }
            // What the chosen account is called (never a secret), from the list, else from one just connected before the
            // list has it.
            const resolved = availableCredentialsRef.current.find((c) => c.id === credentialId) || knownCredential;
            const credentialMeta: Record<string, AccountMeta> | undefined =
                resolved && resolved.id === credentialId ? { [credentialId]: { id: resolved.id, name: resolved.name, credential_type: resolved.credential_type } } : undefined;
            changed({ ...cleaned, [credentialType]: credentialId }, credentialMeta, undefined, { credentialType, credentialId: credentialId || null });
        },
        [credentialIds, changed]
    );

    const { accounts: availableCredentials, loading, error: listError, reload: loadCredentials, namesEvery } = host.useAccounts();
    availableCredentialsRef.current = availableCredentials;
    const error = ways.status === 'failed' ? ways.message : listError;

    // The connect flow, open on a way in (its credential type), or on the first; closed once an account exists.
    const [connecting, setConnecting] = useState<string | true | null>(null);

    // The account whose values are being entered again, in place of its picker.
    const [editingCredentialId, setEditingCredentialId] = useState<string | null>(null);
    // What connecting proved for accounts connected or re-keyed here this session, by id. Older accounts carry theirs
    // in metadata.verified_as.
    const [verifications, setVerifications] = useState<Record<string, ConnectionCheck | null>>({});
    const recordVerification = useCallback(
        (credentialId: string, verification: ConnectionCheck | null | undefined) => {
            setVerifications((prev) => ({ ...prev, [credentialId]: verification ?? null }));
            onVerification?.(credentialId, verification ?? null);
        },
        [onVerification]
    );

    const [openDropdownType, setOpenDropdownType] = useState<string | null>(null);
    const [credentialSearchQuery, setCredentialSearchQuery] = useState('');
    const dropdownRef = useRef<HTMLDivElement>(null);
    const searchInputRef = useRef<HTMLInputElement>(null);

    const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
    const [credentialToDelete, setCredentialToDelete] = useState<{ id: string; name: string; type: string } | null>(null);

    const [shareCredential, setShareCredential] = useState<{ id: string; name: string } | null>(null);

    // Close the menu on a click outside it.
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) setOpenDropdownType(null);
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    useEffect(() => {
        if (openDropdownType && searchInputRef.current) searchInputRef.current.focus();
    }, [openDropdownType]);

    useEffect(() => {
        if (!openDropdownType) setCredentialSearchQuery('');
    }, [openDropdownType]);

    // A compact host picks the newest account of each kind for the person to confirm, rather than leave a quiet picker
    // to notice. The host echoes a choice back through `credentialIds` a render later, so each kind is chosen once
    // (re-choosing on every render until the echo lands once flooded a host with hundreds of saves).
    const autoSelectedTypesRef = useRef<Set<string>>(new Set());
    useEffect(() => {
        if (!compact || requiredCredentials.length === 0 || availableCredentials.length === 0) return;
        const nextCredentialIds = { ...credentialIds };
        const chosen: string[] = [];
        for (const req of requiredCredentials) {
            if (nextCredentialIds[req.credential_type]?.trim()) continue;
            if (autoSelectedTypesRef.current.has(req.credential_type)) continue;
            const match = availableCredentials.find((c) => c.credential_type === req.credential_type && !c.over_cap);
            if (!match) continue;
            nextCredentialIds[req.credential_type] = match.id;
            autoSelectedTypesRef.current.add(req.credential_type);
            chosen.push(req.credential_type);
        }
        if (chosen.length) {
            onChange?.(nextCredentialIds);
            for (const type of chosen) {
                if (save) save(type, nextCredentialIds[type]).catch((err: unknown) => toast.error('The step’s account couldn’t be saved', { description: err instanceof Error ? err.message : String(err) }));
            }
        }
    }, [availableCredentials, compact, credentialIds, onChange, requiredCredentials, save]);

    const cancelEdit = useCallback(() => setEditingCredentialId(null), []);

    /** Entering an account's values again: in place where the host keeps them, else at its connect page. */
    const startEditCredential = useCallback(
        (credential: StepAccount) => {
            if (connecting_.Rekey) {
                setEditingCredentialId(credential.id);
                return;
            }
            if (!client) throw new Error('Connecting an account again needs the platform client a ClientProvider gives.');
            connecting_.reconnect({ credentialType: credential.credential_type, credentialId: credential.id }, client, app);
        },
        [connecting_, client, app]
    );

    const openDeleteDialog = useCallback((credentialId: string, credentialName: string, credentialType: string) => {
        setCredentialToDelete({ id: credentialId, name: credentialName, type: credentialType });
        setIsDeleteDialogOpen(true);
    }, []);

    const confirmDeleteCredential = useCallback(async () => {
        if (!credentialToDelete || !remove) return;
        try {
            const refused = await remove(credentialToDelete.id);
            if (refused === null) {
                await loadCredentials();
                // Others looking at the step drop it too; the step lets go of it if it pointed there.
                const newCredentialIds = { ...credentialIds };
                if (newCredentialIds[credentialToDelete.type] === credentialToDelete.id) delete newCredentialIds[credentialToDelete.type];
                onChange?.(newCredentialIds, undefined, [credentialToDelete.id]);
            } else {
                toast.error(refused);
            }
        } catch (err) {
            console.error('[NodeCredentials] Error deleting credential:', err);
            toast.error('Failed to delete credential');
        } finally {
            setCredentialToDelete(null);
        }
    }, [credentialToDelete, remove, loadCredentials, credentialIds, onChange]);

    if (loading) {
        return <div className="py-6 text-center text-[13px] text-muted-foreground">Loading your accounts…</div>;
    }

    if (error) {
        return (
            <p role="alert" className="flex items-center gap-2 text-[13px] text-red-600 dark:text-red-400">
                <AlertCircle className="h-4 w-4 shrink-0" />
                {error}
            </p>
        );
    }

    // A type's own account form, where the host has one.
    if (CustomCredentialForm) {
        return <CustomCredentialForm nodeData={nodeData} credentialIds={credentialIds} onCredentialIdsChange={handleCredentialIdsChange} compact={compact} onConnected={onConnected} />;
    }

    if (requiredCredentials.length === 0) {
        return <p className="py-6 text-center text-[13px] text-muted-foreground">This step needs no account.</p>;
    }

    // A notice said once (deduped across the ways in), e.g. an integration unavailable while its app awaits approval.
    const credentialNotices = Array.from(new Set(requiredCredentials.map((req) => noticeOf(req.schema)).filter((notice): notice is string => Boolean(notice))));

    // A picker for each kind of account the person has (or the step already points at).
    const pickers = requiredCredentials
        .map((req) => ({
            req,
            matching: availableCredentials.filter((cred) => cred.credential_type === req.credential_type && !cred.over_cap).sort((a, b) => deadRank(a) - deadRank(b)),
            vars: credentialVariables?.filter((v) => v.credentialTypes.length === 0 || v.credentialTypes.includes(req.credential_type)) ?? [],
        }))
        .filter(({ req, matching, vars }) => matching.length > 0 || vars.length > 0 || !!credentialIds[req.credential_type]);

    // A WhatsApp number whose session died is repaired by scanning again in place, never by minting a duplicate.
    const qrRepair = requiredCredentials
        .filter((req) => isQRScan(req.schema))
        .map((req) => availableCredentials.find((c) => c.id === credentialIds[req.credential_type]))
        .find((cred): cred is StepAccount => !!cred && isDisconnected(cred) && !cred.revoked_at);

    // The health of what the step points at: a revoked (or vanished) account says why runs will fail.
    const healthOf = (selectedCredentialId: string | undefined): 'ok' | 'revoked' | 'disconnected' | 'unknown' => {
        if (!selectedCredentialId || selectedCredentialId.startsWith('{{')) return 'ok';
        // The full list (not the type- and cap-filtered view), so an over-cap account doesn't false-alarm.
        const fullRow = availableCredentials.find((c) => c.id === selectedCredentialId);
        // An account this panel just connected is real before the list refresh lands.
        const justMinted = mintedCredentialIdsRef.current.has(selectedCredentialId);
        if (fullRow?.revoked_at) return 'revoked';
        if (fullRow && isDisconnected(fullRow)) return 'disconnected';
        // Gone, or not the person's: said only where the list names every account a step can hold.
        if (!fullRow && namesEvery && availableCredentials.length > 0 && !justMinted) return 'unknown';
        return 'ok';
    };
    const anyUnhealthy = requiredCredentials.some((req) => healthOf(credentialIds[req.credential_type]) !== 'ok');
    // A QR shows unasked for a first number, or once "Connect another account" asks to add one. Otherwise a spare one
    // beside a number that can be picked invites a re-scan that rebinds it, and a dead one waits for its Reconnect click.
    const anyNumber = requiredCredentials
        .filter((req) => isQRScan(req.schema))
        .some((req) => availableCredentials.some((c) => c.credential_type === req.credential_type && !c.over_cap && !c.revoked_at));
    const connectOpen = connecting !== null || pickers.length === 0 || anyUnhealthy || !!qrRepair;

    const editing = pickers.flatMap(({ req, matching }) => matching.filter((c) => c.id === editingCredentialId).map((cred) => ({ req, cred })))[0];
    const Rekey = connecting_.Rekey;

    const landed = (credential: LandedAccount, verification: ConnectionCheck | null) => {
        mintedCredentialIdsRef.current.add(credential.id);
        handleCredentialSelect(credential.credential_type, credential.id, credential);
        recordVerification(credential.id, verification);
        setConnecting(null);
        void loadCredentials();
        onConnected?.(credential.id);
    };

    const InPlace = connecting_.InPlace;
    const connectKey = typeof connecting === 'string' ? connecting : (qrRepair?.id ?? 'connect');

    return (
        // A form's measure, not the panel's: the node panel can span the whole canvas.
        <div className="max-w-xl space-y-5" data-testid="node-credentials">
            {credentialNotices.map((notice) => (
                <p key={notice} className="flex items-start gap-2 text-[13px] leading-relaxed text-muted-foreground">
                    <Info className="mt-0.5 h-4 w-4 shrink-0" />
                    {notice}
                </p>
            ))}

            {usageBasedBillingAvailable && <p className="text-[13px] leading-relaxed text-muted-foreground">Optional. With no account here, NoClick’s own key runs it and bills the usage.</p>}

            {pickers.map(({ req, matching, vars }) => {
                const selectedCredentialId = credentialIds[req.credential_type];
                const selectedCredential = matching.find((c) => c.id === selectedCredentialId);
                const health = healthOf(selectedCredentialId);
                const filteredCredentials = fuzzyFilter(matching, credentialSearchQuery, (cred) => [{ text: cred.name.toLowerCase(), weight: 1, fuzzy: true }]);
                // One picker reads "Account"; several are named by their way in ("Sign in with Notion", "Integration token").
                const label = pickers.length > 1 ? methodName(copyMethodOf(methodFromRequirement(req)), app) : 'Account';

                if (editing?.req === req && Rekey) {
                    return (
                        <Rekey
                            key={`${req.credential_type}:${editing.cred.id}`}
                            credentialId={editing.cred.id}
                            credentialType={req.credential_type}
                            name={editing.cred.name}
                            label={req.label}
                            schema={req.schema}
                            app={app}
                            onCancel={cancelEdit}
                            onSaved={async (verification) => {
                                const credentialId = editing.cred.id;
                                await loadCredentials();
                                recordVerification(credentialId, verification);
                                cancelEdit();
                            }}
                        />
                    );
                }

                return (
                    <div key={req.credential_type}>
                        {(!compact || pickers.length > 1) && <div className={FIELD_LABEL}>{label}</div>}
                        <div className="flex items-center gap-1.5">
                            <div className="relative min-w-0 flex-1" ref={openDropdownType === req.credential_type ? dropdownRef : null}>
                                <button
                                    type="button"
                                    data-testid="credential-dropdown"
                                    aria-haspopup="listbox"
                                    aria-expanded={openDropdownType === req.credential_type}
                                    onClick={() => setOpenDropdownType(openDropdownType === req.credential_type ? null : req.credential_type)}
                                    className="group flex h-10 w-full items-center justify-between rounded-xl border border-border bg-transparent px-3.5 text-left text-[14px] transition-colors hover:border-foreground/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:border-foreground/[0.1]"
                                >
                                    <span
                                        className={cn(
                                            'truncate',
                                            selectedCredentialId?.startsWith('{{')
                                                ? 'text-emerald-600 dark:text-emerald-300'
                                                : selectedCredential?.revoked_at || (selectedCredential && isDisconnected(selectedCredential))
                                                  ? 'text-red-600 dark:text-red-400'
                                                  : selectedCredential || selectedCredentialId
                                                    ? 'text-foreground'
                                                    : 'text-muted-foreground'
                                        )}
                                    >
                                        {selectedCredentialId?.startsWith('{{')
                                            ? credentialVariables?.find((v) => `{{vars.${v.name}}}` === selectedCredentialId)?.name || selectedCredentialId
                                            : selectedCredential
                                              ? `${selectedCredential.name}${selectedCredential.revoked_at ? ' (revoked)' : isDisconnected(selectedCredential) ? ' (disconnected)' : ''}`
                                              : selectedCredentialId
                                                ? 'Connected'
                                                : 'Choose an account'}
                                    </span>
                                    <ChevronDown className={cn('ml-2 h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:text-foreground', openDropdownType === req.credential_type && 'rotate-180')} />
                                </button>

                                {openDropdownType === req.credential_type && (
                                    <div className="absolute z-50 mt-1 w-full overflow-hidden rounded-xl border border-border bg-popover shadow-lg animate-fade-in dark:border-foreground/[0.1]">
                                        <div className="relative border-b border-border dark:border-foreground/[0.08]">
                                            <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                                            <input
                                                ref={searchInputRef}
                                                type="text"
                                                placeholder="Search accounts"
                                                value={credentialSearchQuery}
                                                onChange={(e) => setCredentialSearchQuery(e.target.value)}
                                                className="w-full bg-transparent py-2.5 pl-9 pr-3 text-[13px] text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none"
                                            />
                                        </div>

                                        <div className="max-h-56 overflow-y-auto scrollbar-subtle">
                                            <button
                                                type="button"
                                                onClick={() => {
                                                    handleCredentialSelect(req.credential_type, '');
                                                    setOpenDropdownType(null);
                                                }}
                                                className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] text-muted-foreground transition-colors hover:bg-accent"
                                            >
                                                <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', !selectedCredentialId ? 'bg-muted-foreground' : 'bg-transparent')} />
                                                None
                                            </button>

                                            {/* The workflow's variables that hold an account of this kind. */}
                                            {vars.length > 0 && (
                                                <>
                                                    <div className="px-3 pb-1 pt-2 text-[12px] text-muted-foreground">Variables</div>
                                                    {vars.map((v) => {
                                                        const varRef = `{{vars.${v.name}}}`;
                                                        return (
                                                            <button
                                                                key={varRef}
                                                                type="button"
                                                                onClick={() => {
                                                                    handleCredentialSelect(req.credential_type, varRef);
                                                                    setOpenDropdownType(null);
                                                                }}
                                                                className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] transition-colors hover:bg-accent"
                                                            >
                                                                <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', selectedCredentialId === varRef ? 'bg-emerald-500' : 'bg-transparent')} />
                                                                <span className="text-emerald-600 dark:text-emerald-300">{v.name}</span>
                                                            </button>
                                                        );
                                                    })}
                                                </>
                                            )}

                                            {filteredCredentials.length > 0
                                                ? filteredCredentials.map((cred) => (
                                                      <div key={cred.id} className="flex w-full items-center text-[13px] transition-colors hover:bg-accent">
                                                          <button
                                                              type="button"
                                                              onClick={() => {
                                                                  handleCredentialSelect(req.credential_type, cred.id);
                                                                  setOpenDropdownType(null);
                                                              }}
                                                              className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2 text-left"
                                                          >
                                                              <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', selectedCredentialId === cred.id ? 'bg-foreground' : 'bg-transparent')} />
                                                              <span className={cn('truncate', cred.revoked_at ? 'text-muted-foreground line-through' : isDisconnected(cred) ? 'text-muted-foreground' : 'text-foreground')}>{cred.name}</span>
                                                              {cred.revoked_at ? (
                                                                  <span className="shrink-0 text-[11.5px] text-red-600 dark:text-red-400" title="Disconnected or revoked: connect the account again to use it">
                                                                      Revoked
                                                                  </span>
                                                              ) : isDisconnected(cred) ? (
                                                                  <span className="shrink-0 text-[11.5px] text-red-600 dark:text-red-400" title="The connection dropped: scan a fresh QR code to link it again">
                                                                      Disconnected
                                                                  </span>
                                                              ) : null}
                                                          </button>
                                                          {/* Owner-only actions: none on an account the person doesn't own, and none in a compact host, a
                                                              question that offers picking or connecting only. */}
                                                          {!compact && isOwnedByViewer(cred) && (host.Share || remove) && (
                                                              <div className="flex items-center gap-0.5 pr-1.5">
                                                                  {host.Share && (
                                                                      <button
                                                                          type="button"
                                                                          onClick={(e) => {
                                                                              e.stopPropagation();
                                                                              setShareCredential({ id: cred.id, name: cred.name });
                                                                              setOpenDropdownType(null);
                                                                          }}
                                                                          className="rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                                                                          title="Share"
                                                                          aria-label={`Share ${cred.name}`}
                                                                      >
                                                                          <Share2 className="h-3.5 w-3.5" />
                                                                      </button>
                                                                  )}
                                                                  {remove && (
                                                                      <button
                                                                          type="button"
                                                                          onClick={(e) => {
                                                                              e.stopPropagation();
                                                                              openDeleteDialog(cred.id, cred.name, req.credential_type);
                                                                              setOpenDropdownType(null);
                                                                          }}
                                                                          className="rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-red-600 dark:hover:text-red-400"
                                                                          title="Delete"
                                                                          aria-label={`Delete ${cred.name}`}
                                                                      >
                                                                          <Trash2 className="h-3.5 w-3.5" />
                                                                      </button>
                                                                  )}
                                                              </div>
                                                          )}
                                                      </div>
                                                  ))
                                                : credentialSearchQuery && <div className="px-3 py-2 text-[13px] text-muted-foreground">No match</div>}
                                        </div>

                                        {/* Connecting another opens the connect flow on this way in, below the picker. */}
                                        <button
                                            type="button"
                                            onClick={() => {
                                                setOpenDropdownType(null);
                                                setConnecting(req.credential_type);
                                            }}
                                            className="flex w-full items-center gap-2 border-t border-border px-3 py-2.5 text-left text-[13px] text-foreground transition-colors hover:bg-accent dark:border-foreground/[0.08]"
                                        >
                                            <Plus className="h-3.5 w-3.5" />
                                            Connect another account
                                        </button>
                                    </div>
                                )}
                            </div>

                            {/* Update, Share, Delete: only for the person's OWN account (the owner note says why otherwise); a
                                compact host keeps Update alone. */}
                            {selectedCredential && isOwnedByViewer(selectedCredential) && (
                                <div className="flex items-center">
                                    <button
                                        type="button"
                                        onClick={() => startEditCredential(selectedCredential)}
                                        className="rounded-full p-2 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                                        title="Update"
                                        aria-label={`Update ${selectedCredential.name}`}
                                    >
                                        <Edit2 className="h-3.5 w-3.5" />
                                    </button>
                                    {!compact && (
                                        <>
                                            {host.Share && (
                                                <button
                                                    type="button"
                                                    onClick={() => setShareCredential({ id: selectedCredential.id, name: selectedCredential.name })}
                                                    className="rounded-full p-2 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                                                    title="Share"
                                                    aria-label={`Share ${selectedCredential.name}`}
                                                >
                                                    <Share2 className="h-3.5 w-3.5" />
                                                </button>
                                            )}
                                            {remove && (
                                                <button
                                                    type="button"
                                                    onClick={() => openDeleteDialog(selectedCredential.id, selectedCredential.name, req.credential_type)}
                                                    className="rounded-full p-2 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-red-600 dark:hover:text-red-400"
                                                    title="Delete"
                                                    aria-label={`Delete ${selectedCredential.name}`}
                                                >
                                                    <Trash2 className="h-3.5 w-3.5" />
                                                </button>
                                            )}
                                        </>
                                    )}
                                </div>
                            )}
                        </div>

                        {/* Why the owner-only actions are absent: an owner's account that runs this flow as its owner's, or one
                            shared with the person directly. */}
                        {selectedCredential && !isOwnedByViewer(selectedCredential) && (
                            <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted-foreground">
                                Owned by <span className="text-foreground">{ownerLabel(selectedCredential)}</span>. {selectedCredential.owner_name ? 'It’s shared with this flow.' : 'It’s shared with you; remove it from Connections.'}
                            </p>
                        )}

                        {/* The attached account's health: a revoked (or vanished) one must say WHY runs will fail. */}
                        {health !== 'ok' && (
                            <p data-testid="credential-health-warning" className="mt-1.5 flex items-start gap-1.5 text-[12.5px] leading-relaxed text-red-600 dark:text-red-400">
                                <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                                <span>
                                    {health === 'disconnected'
                                        ? // The provider's check says how to repair it (re-scan a WhatsApp number, reinstall a Discord bot).
                                          (availableCredentials.find((c) => c.id === selectedCredentialId)?.connection_hint ?? 'This connection dropped and nothing is arriving through it. Connect the same account again below.')
                                        : health === 'revoked'
                                          ? 'This account was disconnected or revoked, so runs can’t use it. Connect it again below, or choose another.'
                                          : 'The attached account no longer exists or isn’t yours to use. Connect one below, or choose another.'}
                                </span>
                            </p>
                        )}

                        {/* What connecting proved: an account connected or re-keyed here shows the check's verdict in full, one
                            connected earlier what its record remembers. */}
                        {selectedCredential &&
                            selectedCredentialId &&
                            (selectedCredentialId in verifications ? (
                                <ConnectionVerdict className="mt-3" verification={verifications[selectedCredentialId]} providerLabel={app} accountLine={selectedCredential.metadata?.email as string | undefined} />
                            ) : (
                                <StoredVerdict className="mt-1.5" metadata={selectedCredential.metadata} />
                            ))}
                    </div>
                );
            })}

            {connectOpen ? (
                <div className={cn(pickers.length > 0 && 'border-t border-border pt-5 dark:border-foreground/[0.08]')}>
                    {pickers.length > 0 && (
                        <div className="mb-4 flex items-center justify-between gap-3">
                            <p className="text-[14.5px] font-medium text-foreground">Connect another account</p>
                            {connecting !== null && (
                                <button type="button" onClick={() => setConnecting(null)} className={INLINE_ACTION}>
                                    Never mind
                                </button>
                            )}
                        </div>
                    )}
                    {ways.status === 'ready' && ways.model ? (
                        <ModelConnectInPlace key={connectKey} provider={ways.model} way={requiredCredentials.find((r) => r.credential_type === connecting) ?? requiredCredentials[0]} app={app} onConnected={landed} />
                    ) : (
                        <InPlace
                            key={connectKey}
                            nodeType={nodeType}
                            app={app}
                            integration={ways.status === 'ready' ? ways.integration : null}
                            // Compact surfaces (Setup, the ask drawer, the chat's setup card) belong to someone already asking.
                            ask={!compact}
                            credentialType={typeof connecting === 'string' ? connecting : qrRepair?.credential_type}
                            repairs={qrRepair?.id}
                            autoStart={connecting !== null || !anyNumber}
                            onConnected={landed}
                        />
                    )}
                </div>
            ) : (
                <button type="button" onClick={() => setConnecting(true)} className={cn(INLINE_ACTION, 'inline-flex items-center gap-1.5')}>
                    <Plus className="h-3.5 w-3.5" />
                    Connect another account
                </button>
            )}

            {remove && <DeleteConfirmPopup itemType="Credential" itemName={credentialToDelete?.name} isOpen={isDeleteDialogOpen} onOpenChange={setIsDeleteDialogOpen} onConfirmDelete={confirmDeleteCredential} />}

            {host.Share && <host.Share account={shareCredential} onClose={() => setShareCredential(null)} />}
        </div>
    );
}

/** An agent's AI account connected through `connect.model`, from a button in place: the key of the provider its model
 *  names, with the platform client a ClientProvider above gives. */
function ModelConnectInPlace({ provider, way, app, onConnected }: { provider: string; way: CredentialRequirement; app: string; onConnected: (account: LandedAccount, check: ConnectionCheck | null) => void }) {
    const Connect = useSlot(CONNECT_MODEL);
    const client = useClient();
    const [open, setOpen] = useState(false);
    return (
        <div className="space-y-2" data-testid="connect-in-place">
            <p className="text-[13px] leading-relaxed text-muted-foreground">The agent runs on your {app} account.</p>
            <button type="button" onClick={() => setOpen(true)} className={cn(INLINE_ACTION, 'inline-flex items-center gap-1.5')}>
                <Plus className="h-3.5 w-3.5" />
                Connect an AI account
            </button>
            <Connect
                credentialType={open ? way.credential_type : null}
                integration={open ? provider : null}
                title={`Connect your ${app} account`}
                others={[]}
                client={client}
                onOpenChange={setOpen}
                onConnected={(credentialId) => onConnected({ id: credentialId, name: way.label, credential_type: way.credential_type }, null)}
            />
        </div>
    );
}
