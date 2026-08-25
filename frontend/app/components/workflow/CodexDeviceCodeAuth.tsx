// Codex ChatGPT device code OAuth flow component.
// Handles the full device code auth lifecycle: start → show code → poll → complete.

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { ExternalLink, Loader2, Check, AlertCircle } from 'lucide-react';
import { sendEventAsync } from '~/lib/socket-sender';
import { useAgentOAuthAnalytics } from '~/hooks/useAgentOAuthAnalytics';
import { isPrimaryAgentCredentialKey } from '~/lib/agentCredentialModel';

interface CodexDeviceCodeAuthProps {
    credentialIds: Record<string, string>;
    onCredentialIdsChange: (credentialIds: Record<string, string>) => void;
    onCredentialCreated: () => Promise<void>;
    // Transport override (default: socket). The public credential-provide page
    // passes an HTTP shim so this exact component works without an authed socket.
    sendEvent?: (event: any) => Promise<any>;
}

interface DeviceCodeState {
    status: 'idle' | 'loading' | 'awaiting_approval' | 'polling' | 'completed' | 'error';
    verificationUrl?: string;
    userCode?: string;
    deviceAuthId?: string;
    interval?: number;
    message?: string;
}

export function CodexDeviceCodeAuth({
    credentialIds,
    onCredentialIdsChange,
    onCredentialCreated,
    sendEvent,
}: CodexDeviceCodeAuthProps) {
    const [state, setState] = useState<DeviceCodeState>({ status: 'idle' });
    const analytics = useAgentOAuthAnalytics('codex');
    const send = useMemo(() => sendEvent ?? sendEventAsync, [sendEvent]);
    const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    useEffect(() => {
        return () => {
            if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
        };
    }, []);

    const startFlow = useCallback(async () => {
        setState({ status: 'loading' });
        analytics.started();
        try {
            const response = await send({
                event_name: 'codex:auth:start',
                request_id: `codex-auth-start-${Date.now()}`,
            });
            if (response?.success) {
                setState({
                    status: 'awaiting_approval',
                    verificationUrl: response.verification_url,
                    userCode: response.user_code,
                    deviceAuthId: response.device_auth_id,
                    interval: response.interval || 5,
                    message: response.message,
                });
                window.open(response.verification_url, '_blank');
            } else {
                analytics.failed('start', response?.message);
                setState({
                    status: 'error',
                    message: response?.message || 'Failed to start device code flow',
                });
            }
        } catch (err) {
            analytics.failed('start', err instanceof Error ? err.message : String(err));
            setState({
                status: 'error',
                message: err instanceof Error ? err.message : 'Failed to start device code flow',
            });
        }
    }, [analytics, send]);

    const poll = useCallback(async () => {
        setState(prev => {
            if (!prev.deviceAuthId || !prev.userCode) return prev;
            return { ...prev, status: 'polling' };
        });

        const currentState = state;
        if (!currentState.deviceAuthId || !currentState.userCode) return;

        try {
            const response = await send({
                event_name: 'codex:auth:poll',
                request_id: `codex-auth-poll-${Date.now()}`,
                device_auth_id: currentState.deviceAuthId,
                user_code: currentState.userCode,
            });
            if (response?.success && response.status === 'completed') {
                analytics.completed();
                setState({ status: 'completed', message: response.message });
                await onCredentialCreated();
                if (response.credential_id) {
                    const newCredentialIds = { ...credentialIds };
                    Object.keys(newCredentialIds).forEach(key => {
                        if (isPrimaryAgentCredentialKey(key)) delete newCredentialIds[key];
                    });
                    newCredentialIds['agent_codex_oauth'] = response.credential_id;
                    onCredentialIdsChange(newCredentialIds);
                }
            } else if (response?.success && response.status === 'pending') {
                setState(prev => ({ ...prev, status: 'awaiting_approval' }));
                pollTimerRef.current = setTimeout(poll, (currentState.interval || 5) * 1000);
            } else {
                analytics.failed('poll', response?.message);
                setState({
                    status: 'error',
                    message: response?.message || 'Device code flow failed',
                });
            }
        } catch (err) {
            analytics.failed('poll', err instanceof Error ? err.message : String(err));
            setState({
                status: 'error',
                message: err instanceof Error ? err.message : 'Poll failed',
            });
        }
    }, [state.deviceAuthId, state.userCode, state.interval, onCredentialCreated, credentialIds, onCredentialIdsChange, analytics, send]);

    const cancel = useCallback(() => {
        if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
        setState({ status: 'idle' });
    }, []);

    if (state.status === 'idle') {
        return (
            <div className="space-y-1.5">
                <button
                    onClick={startFlow}
                    className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs text-foreground/80 hover:text-foreground bg-muted dark:bg-zinc-800/50 hover:bg-accent border border-border dark:border-zinc-700 hover:border-muted-foreground/40 dark:hover:border-zinc-600 rounded-lg transition-all"
                >
                    <ExternalLink className="h-3.5 w-3.5" />
                    Connect with ChatGPT account
                </button>
                <p className="text-[11px] text-muted-foreground/70 dark:text-zinc-600 text-center">
                    Requires{' '}
                    <a href="https://chatgpt.com/settings/security" target="_blank" rel="noopener noreferrer" className="text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 underline">
                        device code auth
                    </a>
                    {' '}enabled in ChatGPT security settings
                </p>
            </div>
        );
    }

    if (state.status === 'loading') {
        return (
            <div className="flex items-center justify-center gap-2 px-3 py-3 text-xs text-muted-foreground bg-card/50 border border-border rounded-lg">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Starting device code flow...
            </div>
        );
    }

    if (state.status === 'awaiting_approval' || state.status === 'polling') {
        return (
            <div className="p-4 rounded-lg bg-card/50 border border-border space-y-3">
                <div className="text-[11px] text-muted-foreground uppercase tracking-wider">
                    ChatGPT Authentication
                </div>
                <div className="text-center space-y-2">
                    <p className="text-xs text-muted-foreground">Enter this code at the verification page:</p>
                    <div className="font-mono text-2xl font-bold text-foreground tracking-widest bg-secondary rounded-lg py-3 select-all">
                        {state.userCode}
                    </div>
                    {state.verificationUrl && (
                        <a
                            href={state.verificationUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 transition-colors"
                        >
                            Open verification page <ExternalLink className="h-3 w-3" />
                        </a>
                    )}
                </div>
                <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground dark:text-zinc-500">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    {state.status === 'polling' ? 'Checking...' : 'Waiting for approval...'}
                </div>
                <div className="flex gap-2">
                    <button
                        onClick={cancel}
                        className="flex-1 px-3 py-2 text-xs text-muted-foreground hover:text-foreground/80 bg-card hover:bg-accent border border-border rounded-lg transition-all"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={poll}
                        disabled={state.status === 'polling'}
                        className="flex-1 px-3 py-2 text-xs text-foreground bg-foreground/20 hover:bg-foreground/25 disabled:bg-muted disabled:text-muted-foreground/70 dark:disabled:text-zinc-600 disabled:cursor-not-allowed border border-border dark:border-zinc-700 rounded-lg transition-all"
                    >
                        {state.status === 'polling' ? 'Checking...' : "I've approved it"}
                    </button>
                </div>
            </div>
        );
    }

    if (state.status === 'completed') {
        return (
            <div className="space-y-2">
                <div className="flex items-center gap-2 text-xs text-green-600 dark:text-green-400 bg-green-500/10 border border-green-500/20 rounded-lg px-3 py-2">
                    <Check className="h-3.5 w-3.5 flex-shrink-0" />
                    <span>{state.message || 'ChatGPT account connected'}</span>
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
                <span>{state.message || 'Device code flow failed'}</span>
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
