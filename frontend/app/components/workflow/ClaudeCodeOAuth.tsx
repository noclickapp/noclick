// Claude Code OAuth PKCE authentication component.
// Handles the full OAuth flow: generate auth URL → user authenticates → paste code → exchange for tokens.

import { useState, useCallback, useMemo, useRef } from 'react';
import { ExternalLink, Loader2, Check, AlertCircle } from 'lucide-react';
import { Button } from '~/components/ui/button';
import { sendEventAsync } from '~/lib/socket-sender';
import { useAgentOAuthAnalytics } from '~/hooks/useAgentOAuthAnalytics';
import { isPrimaryAgentCredentialKey } from '~/lib/agentCredentialModel';
import type { AgentOAuthComponentProps } from './AgentOAuthConnect';
import { SignInStarting } from './DeviceCodePanel';

interface ClaudeCodeOAuthProps {
    credentialIds: Record<string, string>;
    onCredentialIdsChange: (credentialIds: Record<string, string>) => void;
    onCredentialCreated: () => Promise<void>;
    // Transport override (default: socket); the public provide page passes an HTTP shim.
    sendEvent?: (event: any) => Promise<any>;
    /** See AgentOAuthComponentProps.renderStart. */
    renderStart?: AgentOAuthComponentProps['renderStart'];
}

interface OAuthState {
    status: 'idle' | 'loading' | 'awaiting_code' | 'exchanging' | 'completed' | 'error';
    authUrl?: string;
    authSessionId?: string;
    message?: string;
    credentialId?: string;
}

export function ClaudeCodeOAuth({
    credentialIds,
    onCredentialIdsChange,
    onCredentialCreated,
    sendEvent,
    renderStart,
}: ClaudeCodeOAuthProps) {
    const [state, setState] = useState<OAuthState>({ status: 'idle' });
    const [pastedCode, setPastedCode] = useState('');
    const [addingAccount, setAddingAccount] = useState(false);
    const analytics = useAgentOAuthAnalytics('claude_code');
    const send = useMemo(() => sendEvent ?? sendEventAsync, [sendEvent]);
    const exchanging = useRef(false);
    const credentialId = addingAccount ? undefined : credentialIds.agent_claude_code_oauth;

    const startFlow = useCallback(async () => {
        setState({ status: 'loading' });
        setPastedCode('');
        analytics.started();
        try {
            const response = await send({
                event_name: 'claude-code:auth:start',
                request_id: `claude-code-auth-start-${Date.now()}`,
                credential_id: credentialId,
            });
            if (response?.success) {
                setState({
                    status: 'awaiting_code',
                    authUrl: response.auth_url,
                    authSessionId: response.auth_session_id,
                    credentialId,
                });
                window.open(response.auth_url, '_blank');
            } else {
                analytics.failed('start', response?.message);
                setState({
                    status: 'error',
                    message: response?.message || response?.error || 'Failed to start OAuth flow',
                });
            }
        } catch (err) {
            analytics.failed('start', err instanceof Error ? err.message : String(err));
            setState({
                status: 'error',
                message: err instanceof Error ? err.message : 'Failed to start OAuth flow',
            });
        }
    }, [analytics, send, credentialId]);

    const exchangeCode = useCallback(async () => {
        if (!pastedCode.trim() || !state.authSessionId || exchanging.current) return;
        exchanging.current = true;
        setState(prev => ({ ...prev, status: 'exchanging' }));
        try {
            const response = await send({
                event_name: 'claude-code:auth:exchange',
                request_id: `claude-code-auth-exchange-${Date.now()}`,
                auth_session_id: state.authSessionId,
                authorization_code: pastedCode.trim(),
                credential_id: state.credentialId,
            });
            if (response?.success) {
                analytics.completed();
                setState({ status: 'completed', message: response.message });
                await onCredentialCreated().catch(() => {
                    setState({ status: 'completed', message: 'Connected. Refresh the saved connections list to see the updated account.' });
                });
                if (response.credential_id) {
                    const newCredentialIds = { ...credentialIds };
                    Object.keys(newCredentialIds).forEach(key => {
                        if (isPrimaryAgentCredentialKey(key)) delete newCredentialIds[key];
                    });
                    newCredentialIds['agent_claude_code_oauth'] = response.credential_id;
                    onCredentialIdsChange(newCredentialIds);
                }
                setPastedCode('');
            } else {
                const message = response?.message || response?.error || 'Failed to exchange code';
                analytics.failed('exchange', message);
                setState({ status: 'error', message });
                setPastedCode('');
            }
        } catch (err) {
            analytics.failed('exchange', err instanceof Error ? err.message : String(err));
            setState({ status: 'error', message: `${err instanceof Error ? err.message : 'Exchange failed'}. Check saved connections before starting a new sign-in.` });
            setPastedCode('');
            try {
                await onCredentialCreated();
            } catch {
                setState({ status: 'error', message: 'The sign-in result could not be verified. Refresh the saved connections list before starting another sign-in.' });
            }
        } finally {
            exchanging.current = false;
        }
    }, [pastedCode, state.authSessionId, state.credentialId, onCredentialCreated, credentialIds, onCredentialIdsChange, analytics, send]);

    const cancel = useCallback(() => {
        if (exchanging.current) return;
        setState({ status: 'idle' });
        setPastedCode('');
        setAddingAccount(false);
    }, []);

    if (state.status === 'idle') {
        const note = (
            <>
                {credentialId ? 'Your saved connection is selected. Reconnect only if it stopped working.' : 'For Claude Pro, Max, Teams, or Enterprise subscribers'}
            </>
        );
        if (renderStart) return <>{renderStart(startFlow, note)}</>;
        return (
            <div className="space-y-1.5">
                <button
                    onClick={startFlow}
                    className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs text-foreground/80 hover:text-foreground bg-muted dark:bg-zinc-800/50 hover:bg-accent border border-border dark:border-zinc-700 hover:border-muted-foreground/40 dark:hover:border-zinc-600 rounded-full transition-all"
                >
                    <ExternalLink className="h-3.5 w-3.5" />
                    {credentialId ? 'Reconnect selected Claude account' : 'Connect with Claude account'}
                </button>
                <p className="text-[11px] text-muted-foreground/70 dark:text-zinc-600 text-center">
                    {note}
                </p>
            </div>
        );
    }

    if (state.status === 'loading') {
        return <SignInStarting />;
    }

    if (state.status === 'awaiting_code' || state.status === 'exchanging') {
        const confirming = state.status === 'exchanging';
        return (
            <div className="space-y-3">
                <p className="text-[14.5px] font-medium text-foreground">Finish signing in with Claude</p>
                <ol className="list-decimal space-y-1 pl-4 text-[13px] text-muted-foreground">
                    <li>
                        Sign in on{' '}
                        {state.authUrl ? (
                            <a
                                href={state.authUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="font-medium text-foreground underline decoration-foreground/30 underline-offset-4 transition-colors hover:decoration-foreground"
                            >
                                Claude’s sign-in page
                            </a>
                        ) : (
                            'Claude’s sign-in page'
                        )}
                        .
                    </li>
                    <li>Copy the code it shows you and paste it here.</li>
                </ol>
                <input
                    type="text"
                    value={pastedCode}
                    onChange={(e) => setPastedCode(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter' && pastedCode.trim()) exchangeCode(); }}
                    placeholder="Paste the code"
                    aria-label="Authorization code"
                    className="h-10 w-full rounded-xl border border-border bg-transparent px-3 font-mono text-[13.5px] text-foreground outline-none transition-colors placeholder:font-sans placeholder:text-[hsl(var(--placeholder))] focus:border-foreground/25 dark:border-foreground/[0.1]"
                    disabled={confirming}
                />
                {state.message && (
                    <p className="flex items-center gap-1.5 text-[13px] text-red-600 dark:text-red-400">
                        <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                        {state.message}
                    </p>
                )}
                <div className="flex items-center justify-end gap-1">
                    <button type="button" onClick={cancel} disabled={confirming} className="inline-flex h-9 items-center rounded-full px-3 text-[13px] text-muted-foreground transition-colors hover:text-foreground">
                        Cancel
                    </button>
                    <Button type="button" size="sm" onClick={exchangeCode} disabled={!pastedCode.trim() || confirming}>
                        {confirming && <Loader2 className="h-4 w-4 animate-spin" />}
                        {confirming ? 'Confirming…' : 'Confirm'}
                    </Button>
                </div>
            </div>
        );
    }

    if (state.status === 'completed') {
        return (
            <div className="space-y-2">
                <div className="flex items-center gap-2 text-xs text-green-600 dark:text-green-400 bg-green-500/10 border border-green-500/20 rounded-lg px-3 py-2">
                    <Check className="h-3.5 w-3.5 flex-shrink-0" />
                    <span>{state.message || 'Claude account connected'}</span>
                </div>
                <button
                    onClick={() => { setAddingAccount(true); setState({ status: 'idle' }); }}
                    className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 bg-muted/50 dark:bg-zinc-900/50 hover:bg-accent dark:hover:bg-zinc-900 border border-border hover:border-muted-foreground/40 dark:hover:border-zinc-700 rounded-full transition-all"
                >
                    <ExternalLink className="h-3.5 w-3.5" />
                    Connect another account
                </button>
            </div>
        );
    }

    // error state
    return (
        <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 space-y-2">
            <div className="flex items-center gap-2 text-xs text-red-600 dark:text-red-400">
                <AlertCircle className="h-3.5 w-3.5 flex-shrink-0" />
                <span>{state.message || 'OAuth flow failed'}</span>
            </div>
            <button
                onClick={() => setState({ status: 'idle' })}
                className="text-xs text-muted-foreground hover:text-foreground/80 transition-colors"
            >
                Try again
            </button>
        </div>
    );
}
