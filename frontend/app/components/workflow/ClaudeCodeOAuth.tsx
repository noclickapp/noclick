// Claude Code OAuth PKCE authentication component.
// Handles the full OAuth flow: generate auth URL → user authenticates → paste code → exchange for tokens.

import { useState, useCallback , useMemo } from 'react';
import { ExternalLink, Loader2, Check, AlertCircle, ClipboardPaste } from 'lucide-react';
import { sendEventAsync } from '~/lib/socket-sender';
import { useAgentOAuthAnalytics } from '~/hooks/useAgentOAuthAnalytics';
import { isPrimaryAgentCredentialKey } from '~/lib/agentCredentialModel';

interface ClaudeCodeOAuthProps {
    credentialIds: Record<string, string>;
    onCredentialIdsChange: (credentialIds: Record<string, string>) => void;
    onCredentialCreated: () => Promise<void>;
    // Transport override (default: socket); the public provide page passes an HTTP shim.
    sendEvent?: (event: any) => Promise<any>;
}

interface OAuthState {
    status: 'idle' | 'loading' | 'awaiting_code' | 'exchanging' | 'completed' | 'error';
    authUrl?: string;
    authSessionId?: string;
    message?: string;
}

export function ClaudeCodeOAuth({
    credentialIds,
    onCredentialIdsChange,
    onCredentialCreated,
    sendEvent,
}: ClaudeCodeOAuthProps) {
    const [state, setState] = useState<OAuthState>({ status: 'idle' });
    const [pastedCode, setPastedCode] = useState('');
    const analytics = useAgentOAuthAnalytics('claude_code');
    const send = useMemo(() => sendEvent ?? sendEventAsync, [sendEvent]);

    const startFlow = useCallback(async () => {
        setState({ status: 'loading' });
        analytics.started();
        try {
            const response = await send({
                event_name: 'claude-code:auth:start',
                request_id: `claude-code-auth-start-${Date.now()}`,
            });
            if (response?.success) {
                setState({
                    status: 'awaiting_code',
                    authUrl: response.auth_url,
                    authSessionId: response.auth_session_id,
                });
                window.open(response.auth_url, '_blank');
            } else {
                analytics.failed('start', response?.message);
                setState({
                    status: 'error',
                    message: response?.message || 'Failed to start OAuth flow',
                });
            }
        } catch (err) {
            analytics.failed('start', err instanceof Error ? err.message : String(err));
            setState({
                status: 'error',
                message: err instanceof Error ? err.message : 'Failed to start OAuth flow',
            });
        }
    }, [analytics, send]);

    const exchangeCode = useCallback(async () => {
        if (!pastedCode.trim() || !state.authSessionId) return;
        setState(prev => ({ ...prev, status: 'exchanging' }));
        try {
            const response = await send({
                event_name: 'claude-code:auth:exchange',
                request_id: `claude-code-auth-exchange-${Date.now()}`,
                auth_session_id: state.authSessionId,
                authorization_code: pastedCode.trim(),
            });
            if (response?.success) {
                analytics.completed();
                setState({ status: 'completed', message: response.message });
                await onCredentialCreated();
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
                analytics.failed('exchange', response?.message);
                setState(prev => ({
                    ...prev,
                    status: 'awaiting_code',
                    message: response?.message || 'Failed to exchange code',
                }));
            }
        } catch (err) {
            analytics.failed('exchange', err instanceof Error ? err.message : String(err));
            setState(prev => ({
                ...prev,
                status: 'awaiting_code',
                message: err instanceof Error ? err.message : 'Exchange failed',
            }));
        }
    }, [pastedCode, state.authSessionId, onCredentialCreated, credentialIds, onCredentialIdsChange, analytics, send]);

    const cancel = useCallback(() => {
        setState({ status: 'idle' });
        setPastedCode('');
    }, []);

    if (state.status === 'idle') {
        return (
            <div className="space-y-1.5">
                <button
                    onClick={startFlow}
                    className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs text-foreground/80 hover:text-foreground bg-muted dark:bg-zinc-800/50 hover:bg-accent border border-border dark:border-zinc-700 hover:border-muted-foreground/40 dark:hover:border-zinc-600 rounded-lg transition-all"
                >
                    <ExternalLink className="h-3.5 w-3.5" />
                    Connect with Claude account
                </button>
                <p className="text-[11px] text-muted-foreground/70 dark:text-zinc-600 text-center">
                    For Claude Pro, Max, Teams, or Enterprise subscribers
                </p>
            </div>
        );
    }

    if (state.status === 'loading') {
        return (
            <div className="flex items-center justify-center gap-2 px-3 py-3 text-xs text-muted-foreground bg-card/50 border border-border rounded-lg">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Preparing authentication...
            </div>
        );
    }

    if (state.status === 'awaiting_code' || state.status === 'exchanging') {
        return (
            <div className="p-4 rounded-lg bg-card/50 border border-border space-y-3">
                <div className="text-[11px] text-muted-foreground uppercase tracking-wider">
                    Claude Authentication
                </div>
                <div className="space-y-2">
                    <p className="text-xs text-muted-foreground">
                        1. Authenticate in the browser window that opened
                    </p>
                    <p className="text-xs text-muted-foreground">
                        2. Copy the authorization code shown after login
                    </p>
                    {state.authUrl && (
                        <a
                            href={state.authUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 transition-colors"
                        >
                            Open authentication page <ExternalLink className="h-3 w-3" />
                        </a>
                    )}
                </div>
                <div className="space-y-2">
                    <label className="block text-xs text-muted-foreground dark:text-zinc-500">Paste authorization code</label>
                    <input
                        type="text"
                        value={pastedCode}
                        onChange={(e) => setPastedCode(e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter' && pastedCode.trim()) exchangeCode(); }}
                        placeholder="Paste code here..."
                        className="w-full px-3 py-2 text-sm bg-card border border-input rounded-md text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-ring/30 transition-colors font-mono"
                        disabled={state.status === 'exchanging'}
                    />
                    <button
                        onClick={exchangeCode}
                        disabled={!pastedCode.trim() || state.status === 'exchanging'}
                        className="w-full px-3 py-2 text-xs text-foreground bg-foreground/20 hover:bg-foreground/25 disabled:bg-muted disabled:text-muted-foreground/70 dark:disabled:text-zinc-600 disabled:cursor-not-allowed border border-border dark:border-zinc-700 rounded-md transition-all flex items-center justify-center gap-2"
                    >
                        {state.status === 'exchanging' ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                            <ClipboardPaste className="h-4 w-4" />
                        )}
                        {state.status === 'exchanging' ? 'Confirming...' : 'Confirm Token'}
                    </button>
                </div>
                {state.message && (
                    <div className="flex items-center gap-2 text-xs text-amber-600 dark:text-amber-400">
                        <AlertCircle className="h-3 w-3 flex-shrink-0" />
                        <span>{state.message}</span>
                    </div>
                )}
                <button
                    onClick={cancel}
                    className="w-full px-3 py-2 text-xs text-muted-foreground hover:text-foreground/80 bg-card hover:bg-accent border border-border rounded-lg transition-all"
                >
                    Cancel
                </button>
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
                    onClick={() => setState({ status: 'idle' })}
                    className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 bg-muted/50 dark:bg-zinc-900/50 hover:bg-accent dark:hover:bg-zinc-900 border border-border hover:border-muted-foreground/40 dark:hover:border-zinc-700 rounded-lg transition-all"
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
