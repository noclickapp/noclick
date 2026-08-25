// AgentEnvVarsSection — picks or creates the `agent_env` credential holding the
// agent's sandbox environment variables, an arbitrary {NAME: value} bundle injected
// into the sandbox shell so the model can call APIs NoClick has no node for
// (curl -H "...$STRIPE_KEY").
//
// Rendered inside AgentCredentialsForm and stored in the node's credentialIds map
// under `agent_env` — the canonical reference location, which is what the pre-delete
// impact scan and workflow_authorized_credentials read. It is a SECONDARY credential
// (it never authenticates the agent), so isPrimaryAgentCredentialKey keeps the
// model-credential purges from deleting it.

import { type ReactElement, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, Check, ChevronDown, Edit2, Loader2, Plus, Trash2, X } from 'lucide-react';
import { sendEventAsync } from '~/lib/socket-sender';
import { useCredentialOAuth } from '~/hooks/useCredentialOAuth';
import {
    invalidateCredentialsCache,
    removeCredentialsFromCache,
} from '~/utils/credentialAutoSelect';
import { EnvVarRowsEditor } from './EnvVarRowsEditor';
import { FieldRequirementBadge } from './FieldRequirementBadge';
import {
    AGENT_ENV_CREDENTIAL_TYPE,
    blankValueNames,
    parseRequestedEnvNames,
    rowsToEnv,
    type EnvRow,
} from './agentEnvVars';

// Matches the name input on the sibling credential-create form.
const inputClasses =
    'w-full px-3 py-2 text-sm bg-card border border-input rounded-md text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-foreground/20 transition-colors';

interface AgentEnvVarsSectionProps {
    credentialIds: Record<string, string>;
    onCredentialIdsChange: (ids: Record<string, string>) => void;
    /** Variable names the AI builder declared this agent needs (node config
     *  `agent_env_requested`). Surfaced as a prompt + a one-click pre-seed. */
    requestedEnvVars?: unknown[];
}

const emptyRow = (): EnvRow => ({ key: '', value: '' });

export function AgentEnvVarsSection({
    credentialIds,
    onCredentialIdsChange,
    requestedEnvVars,
}: AgentEnvVarsSectionProps): ReactElement {
    const { availableCredentials, loading, loadCredentials } = useCredentialOAuth();

    const selectedId: string = credentialIds[AGENT_ENV_CREDENTIAL_TYPE] || '';
    const requestedNames = useMemo(
        () => parseRequestedEnvNames(requestedEnvVars),
        [requestedEnvVars]
    );
    // The builder asked for vars and none are attached yet: skip the "Provide
    // values" click and open straight into the pre-seeded form (the explanation
    // rides along inside it). Cancel drops back to the picker for anyone who'd
    // rather select an existing set. Captured at mount — a lazy initializer.
    const [creating, setCreating] = useState(() => requestedNames.length > 0 && !selectedId);
    const [rows, setRows] = useState<EnvRow[]>(() =>
        requestedNames.length > 0 && !selectedId
            ? requestedNames.map(n => ({ key: n, value: '' }))
            : [emptyRow()]
    );

    const [isOpen, setIsOpen] = useState(false);
    // Id of the set being edited, or null when the form is creating a new one.
    const [editingId, setEditingId] = useState<string | null>(null);
    const [newName, setNewName] = useState('');
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const containerRef = useRef<HTMLDivElement>(null);

    // Writes only our own key — the model credential (and any OAuth alias) in the
    // same map is left untouched.
    const setEnvCredential = useCallback(
        (credentialId: string | null) => {
            const next = { ...credentialIds };
            if (credentialId) next[AGENT_ENV_CREDENTIAL_TYPE] = credentialId;
            else delete next[AGENT_ENV_CREDENTIAL_TYPE];
            onCredentialIdsChange(next);
        },
        [credentialIds, onCredentialIdsChange]
    );

    const envCredentials = useMemo(
        () => availableCredentials.filter(c => c.credential_type === AGENT_ENV_CREDENTIAL_TYPE),
        [availableCredentials]
    );
    const selected = useMemo(
        () => envCredentials.find(c => c.id === selectedId),
        [envCredentials, selectedId]
    );

    /** Open the create form pre-seeded with the requested variable names, so the
     *  user only fills values. Used for the mount-time auto-open and as the
     *  re-seed path if the user cancels and clicks "Create new variable set". */
    const startFromRequest = useCallback(() => {
        setRows(requestedNames.map(n => ({ key: n, value: '' })));
        setNewName('');
        setEditingId(null);
        setCreating(true);
        setError(null);
        setIsOpen(false);
    }, [requestedNames]);

    useEffect(() => {
        const handler = (e: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
                setIsOpen(false);
            }
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);

    const resetForm = useCallback(() => {
        setCreating(false);
        setEditingId(null);
        setRows([emptyRow()]);
        setNewName('');
        setError(null);
    }, []);

    /** Open the form on an existing set. Variable NAMES prefill (they're already
     *  shown as chips); VALUES start empty because the platform never returns
     *  decrypted secrets to the browser — the same rule NodeCredentials'
     *  startEditCredential follows ("user will need to re-enter for security"). */
    const startEdit = useCallback(() => {
        if (!selected) return;
        const names = (selected.metadata as { var_names?: string[] } | undefined)?.var_names;
        setRows(names?.length ? names.map(n => ({ key: n, value: '' })) : [emptyRow()]);
        setNewName(selected.name || '');
        setEditingId(selected.id);
        setCreating(true);
        setError(null);
        setIsOpen(false);
    }, [selected]);

    const handleCreate = useCallback(async () => {
        setError(null);
        let env: Record<string, string>;
        try {
            env = rowsToEnv(rows);
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
            return;
        }
        if (Object.keys(env).length === 0) {
            setError('Add at least one variable.');
            return;
        }
        // credential:update REPLACES the blob, and the browser never holds the old
        // values, so a blank value would silently wipe a working key rather than
        // leave it alone. Refuse instead.
        const blanks = blankValueNames(env);
        if (editingId && blanks.length) {
            setError(
                `Re-enter a value for ${blanks.map(b => `$${b}`).join(', ')} — saving ` +
                `replaces the whole set, so a blank would erase the stored value.`
            );
            return;
        }

        setSaving(true);
        try {
            // Names only — lets the picker show what's in the bundle without
            // decrypting it. Values are never returned to the BROWSER; they do
            // reach the sandbox, where the agent can read them via bash.
            const metadata = { var_names: Object.keys(env) };
            const response = await sendEventAsync(
                editingId
                    ? {
                          event_name: 'credential:update',
                          request_id: `update-agent-env-${Date.now()}`,
                          credential_id: editingId,
                          name: newName.trim() || undefined,
                          credential_data: { env },
                          metadata,
                      }
                    : {
                          event_name: 'credential:create',
                          request_id: `create-agent-env-${Date.now()}`,
                          name:
                              newName.trim() ||
                              `Agent env vars - ${new Date().toLocaleDateString()}`,
                          credential_type: AGENT_ENV_CREDENTIAL_TYPE,
                          credential_data: { env },
                          metadata,
                      }
            );
            if (response?.success) {
                invalidateCredentialsCache();
                await loadCredentials();
                // Editing keeps the existing link; creating adopts the new set.
                if (!editingId && response.credential) {
                    setEnvCredential(response.credential.id);
                }
                resetForm();
                setIsOpen(false);
            } else {
                setError(response?.error || response?.message || 'Failed to save variables');
            }
        } catch (e) {
            setError(e instanceof Error ? e.message : 'Failed to create credential');
        } finally {
            setSaving(false);
        }
    }, [rows, newName, editingId, loadCredentials, setEnvCredential, resetForm]);

    const handleDelete = useCallback(
        async (credentialId: string) => {
            try {
                const response = await sendEventAsync({
                    event_name: 'credential:delete',
                    request_id: `delete-agent-env-${Date.now()}`,
                    credential_id: credentialId,
                    confirm: true,
                });
                if (response?.success) {
                    invalidateCredentialsCache();
                    await loadCredentials();
                    removeCredentialsFromCache([credentialId]);
                    if (selectedId === credentialId) setEnvCredential(null);
                }
            } catch {
                // Surfacing a delete failure in the dropdown would trap focus; the
                // credential simply stays listed and the user can retry.
            }
        },
        [loadCredentials, setEnvCredential, selectedId]
    );


    const varNames = (selected?.metadata as { var_names?: string[] } | undefined)?.var_names;

    // Gates the Save button: something worth persisting exists. Keyed on the NAME
    // (an intentionally empty value is legal), matching the sibling form's
    // required-fields-filled gate.
    const hasEnteredVariables = rows.some(r => r.key.trim().length > 0);

    return (
        <div ref={containerRef} className="space-y-1.5">
            {/* Selector — same shape as the model-credential dropdown directly above
                it in this panel, so the two read as one family. Like that one, it is
                only rendered when there is something to select. `selectedId` keeps it
                mounted while the list is still loading, so a linked set never flashes
                as unlinked. */}
            {!creating && (envCredentials.length > 0 || !!selectedId) && (
                <div className="flex items-center gap-1">
                <div className="relative flex-1 min-w-0">
                    <button
                        type="button"
                        aria-expanded={isOpen}
                        onClick={() => setIsOpen(!isOpen)}
                        className="w-full px-3 py-2 text-sm bg-card dark:bg-card/50 border border-border rounded-lg text-left flex items-center justify-between hover:bg-accent dark:hover:bg-card hover:border-foreground/20 transition-all group"
                    >
                        <span
                            className={`truncate ${selected ? 'text-foreground/80' : 'text-muted-foreground dark:text-zinc-500'}`}
                        >
                            {selected ? selected.name : 'Select variable set...'}
                        </span>
                        {loading ? (
                            <Loader2 className="h-3.5 w-3.5 text-muted-foreground dark:text-zinc-500 animate-spin flex-shrink-0 ml-2" />
                        ) : (
                            <ChevronDown
                                className={`h-3.5 w-3.5 text-muted-foreground dark:text-zinc-500 group-hover:text-foreground/70 transition-all flex-shrink-0 ml-2 ${isOpen ? 'rotate-180' : ''}`}
                            />
                        )}
                    </button>

                    {isOpen && (
                        <div className="absolute z-50 w-full mt-1 bg-card border border-border rounded-lg shadow-2xl overflow-hidden animate-fade-in">
                            <div className="max-h-48 overflow-y-auto scrollbar-subtle">
                                <button
                                    type="button"
                                    onClick={() => {
                                        setEnvCredential(null);
                                        setIsOpen(false);
                                    }}
                                    className="w-full px-3 py-2 text-xs text-left hover:bg-accent transition-colors flex items-center justify-between"
                                >
                                    <span className="text-muted-foreground dark:text-zinc-500 italic">
                                        None selected
                                    </span>
                                    {!selectedId && (
                                        <div className="h-1.5 w-1.5 rounded-full bg-muted-foreground dark:bg-zinc-500" />
                                    )}
                                </button>

                                {envCredentials.map(c => (
                                    <div
                                        key={c.id}
                                        className="flex items-center border-t border-border/30 dark:border-zinc-800/30 hover:bg-accent transition-colors group"
                                    >
                                        <button
                                            type="button"
                                            onClick={() => {
                                                setEnvCredential(c.id);
                                                setIsOpen(false);
                                            }}
                                            className="flex-1 px-3 py-2 text-xs text-left flex items-center justify-between min-w-0"
                                        >
                                            <span className="text-foreground/80 truncate">
                                                {c.name}
                                            </span>
                                            {selectedId === c.id && (
                                                <div className="h-1.5 w-1.5 rounded-full bg-muted-foreground flex-shrink-0 ml-2" />
                                            )}
                                        </button>
                                        <button
                                            type="button"
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                handleDelete(c.id);
                                            }}
                                            className="p-2 opacity-0 group-hover:opacity-100 hover:text-red-600 dark:hover:text-red-400 text-muted-foreground dark:text-zinc-500 transition-all flex-shrink-0"
                                            title="Delete variable set"
                                        >
                                            <Trash2 className="h-3 w-3" />
                                        </button>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
                {/* Edit the linked set — mirrors NodeCredentials' per-credential
                    Edit2 action. Only when one is actually selected. */}
                {selected && (
                    <button
                        type="button"
                        onClick={startEdit}
                        className="p-2 hover:bg-accent rounded-lg transition-colors flex-shrink-0"
                        title="Edit variable set"
                    >
                        <Edit2 className="h-3.5 w-3.5 text-muted-foreground dark:text-zinc-500 hover:text-foreground/80" />
                    </button>
                )}
                </div>
            )}

            {/* Standalone create affordance — the same shape every other credential
                group uses, rather than hiding creation inside the dropdown. */}
            {!creating && (
                <button
                    type="button"
                    // Re-seed the requested names if a request is still unfulfilled
                    // (e.g. after cancelling the auto-opened form), else a blank set.
                    onClick={() =>
                        requestedNames.length > 0 && !selectedId
                            ? startFromRequest()
                            : setCreating(true)
                    }
                    className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 bg-card dark:bg-card/50 hover:bg-accent dark:hover:bg-card border border-border hover:border-foreground/20 rounded-lg transition-all"
                >
                    <Plus className="h-3.5 w-3.5" />
                    Create new variable set
                </button>
            )}

            {/* Variable names of the linked set — names only, never values. */}
            {!creating && varNames && varNames.length > 0 && (
                <div className="flex flex-wrap gap-1">
                    {varNames.map(n => (
                        <span
                            key={n}
                            className="px-1.5 py-0.5 rounded bg-foreground/[0.06] border border-foreground/[0.08] text-[11px] font-mono text-muted-foreground dark:text-zinc-400"
                        >
                            ${n}
                        </span>
                    ))}
                </div>
            )}

            {/* Same panel as the credential-create form above: raised surface,
                border, uppercase header and an × — so it reads as a temporary form
                that must be saved or dismissed, not as more inline fields. */}
            {creating && (
                <div className="p-4 rounded-lg bg-card/50 border border-border space-y-3">
                    <div className="flex items-center justify-between mb-2">
                        <div className="text-[11px] text-muted-foreground uppercase tracking-wider">
                            {editingId ? 'Edit Variable Set' : 'New Variable Set'}
                        </div>
                        <button
                            type="button"
                            onClick={resetForm}
                            className="p-1 hover:bg-accent rounded transition-colors"
                            title="Cancel"
                        >
                            <X className="h-3 w-3 text-muted-foreground dark:text-zinc-500" />
                        </button>
                    </div>

                    <div className="space-y-1.5">
                        <label
                            htmlFor="agent-env-set-name"
                            className="flex items-center gap-2 text-xs text-muted-foreground dark:text-zinc-500"
                        >
                            Name
                            <FieldRequirementBadge isRequired={false} />
                        </label>
                        <input
                            id="agent-env-set-name"
                            type="text"
                            value={newName}
                            onChange={e => setNewName(e.target.value)}
                            placeholder="My API keys"
                            className={inputClasses}
                        />
                    </div>

                    {/* Stored values are never sent to the browser, so an edit can
                        only re-set them. Say so up front rather than letting the
                        blank fields read as "unchanged". */}
                    {editingId && (
                        <div className="text-[11px] text-muted-foreground dark:text-zinc-500">
                            Saved values are hidden and can&apos;t be read back — re-enter
                            each one. You can rename, add and remove variables here too.
                        </div>
                    )}

                    {/* Shared rows editor — same one the builder input drawer and
                        the /b bridge page use. */}
                    <EnvVarRowsEditor rows={rows} onChange={setRows} />

                    {error && (
                        <div className="flex items-start gap-2 text-xs text-amber-600 dark:text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
                            <AlertCircle className="h-3.5 w-3.5 flex-shrink-0 mt-px" />
                            <span>{error}</span>
                        </div>
                    )}

                    {/* Typing alone doesn't persist anything — the bundle only exists
                        once it is minted as a credential. Everywhere else in this
                        panel edits autosave, so say so rather than relying on the
                        button being noticed. */}
                    {hasEnteredVariables && !saving && (
                        <div className="text-[11px] text-muted-foreground dark:text-zinc-500">
                            Not saved yet — press Save to store these securely.
                        </div>
                    )}

                    {/* Same action row as the credential-create form above: equal
                        halves, filled primary, disabled until there's something to
                        save (so it visibly lights up once you type a name). */}
                    <div className="flex gap-2 pt-1">
                        <button
                            type="button"
                            onClick={resetForm}
                            className="flex-1 px-3 py-2 text-xs text-muted-foreground hover:text-foreground/80 bg-card hover:bg-accent border border-border rounded-lg transition-all"
                        >
                            Cancel
                        </button>
                        <button
                            type="button"
                            onClick={handleCreate}
                            disabled={saving || !hasEnteredVariables}
                            className="flex-1 px-3 py-2 text-xs text-primary-foreground dark:text-foreground bg-primary dark:bg-zinc-700 hover:bg-primary/90 dark:hover:bg-zinc-600 disabled:bg-muted disabled:text-muted-foreground dark:disabled:text-zinc-600 disabled:cursor-not-allowed border border-transparent dark:border-zinc-700 dark:hover:border-zinc-600 disabled:border-border rounded-lg transition-all flex items-center justify-center gap-1.5"
                        >
                            {saving ? (
                                editingId ? 'Saving...' : 'Creating...'
                            ) : (
                                <>
                                    <Check className="h-3 w-3" /> Save
                                </>
                            )}
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}
