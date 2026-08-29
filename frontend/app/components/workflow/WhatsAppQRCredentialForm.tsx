// WhatsApp QR code credential form component.
// Handles the QR code scanning flow for connecting a WhatsApp account.
// Used by NodeCredentials when a credential has x-credential-type: "qr_scan".
// No API key needed — the server manages the connection. Users are charged $0.99/month.

import { useState, useEffect, useRef, useCallback } from 'react';
import { Check, Loader2, AlertCircle, RefreshCw, Smartphone } from 'lucide-react';
import { sendEventAsync } from '~/lib/socket-sender';
import type { OAuthExchange } from '~/hooks/oauth/OAuthExchangeContext';
import { invalidateCredentialsCache } from '~/utils/credentialAutoSelect';

interface WhatsAppQRCredentialFormProps {
    credentialType: string;
    onCredentialCreated: (credentialId: string) => void;
    // Transport override (default: socket). The public provide page injects an HTTP shim
    // so this exact QR flow works there too, bound to the requester.
    sendEvent?: OAuthExchange;
    // Dead-session recovery: re-scan into THIS credential's existing connection
    // instead of minting a new credential. The scan repairs the credential in
    // place (same id, same webhooks, same billing) — duplicate credentials
    // stack device links until WhatsApp logs all of them out.
    reconnectCredentialId?: string;
    // Mint + show a QR the moment the form mounts (default). Pass false when a
    // usable credential already exists: a QR sitting in the panel reads as
    // "scan me", and every scan of a phone that is already linked rebinds its
    // credential to a fresh connection (2026-08-29 — two needless re-scans).
    // The form then idles behind a button until the user asks for a new link.
    autoStart?: boolean;
    startLabel?: string;
}

type QRFlowState = 'idle' | 'loading' | 'scanning' | 'connected' | 'error';

export const WhatsAppQRCredentialForm = ({
    onCredentialCreated, sendEvent, reconnectCredentialId, autoStart = true,
    startLabel = 'Connect a different WhatsApp number',
}: WhatsAppQRCredentialFormProps) => {
    const [flowState, setFlowState] = useState<QRFlowState>(autoStart ? 'loading' : 'idle');
    const [qrCode, setQrCode] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [phoneNumber, setPhoneNumber] = useState<string | null>(null);
    const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const pollCountRef = useRef(0);
    const startedRef = useRef(false);
    const sendRef = useRef(sendEvent ?? sendEventAsync);
    useEffect(() => { sendRef.current = sendEvent ?? sendEventAsync; }, [sendEvent]);

    const stopPolling = useCallback(() => {
        if (pollIntervalRef.current) {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;
        }
        pollCountRef.current = 0;
    }, []);

    // Clean up polling on unmount
    useEffect(() => {
        return () => {
            if (pollIntervalRef.current) {
                clearInterval(pollIntervalRef.current);
            }
        };
    }, []);

    const startPolling = useCallback((connId: string) => {
        pollCountRef.current = 0;
        pollIntervalRef.current = setInterval(() => {
            pollCountRef.current++;
            if (pollCountRef.current > 24) {
                stopPolling();
                setError('QR code expired.');
                setFlowState('error');
                return;
            }
            pollStatus(connId);
        }, 5000);
    }, [stopPolling]);

    const startQRFlow = useCallback(async () => {
        setFlowState('loading');
        setError(null);

        try {
            const response = await sendRef.current({
                event_name: 'whatsapp:qr:start',
                ...(reconnectCredentialId ? { reconnect_credential_id: reconnectCredentialId } : {}),
            });

            if (!response?.success) {
                setError(response?.message || 'Failed to load QR code');
                setFlowState('error');
                return;
            }

            setQrCode(response.qr_code);
            setFlowState('scanning');
            startPolling(response.connection_id);
        } catch (e) {
            setError(e instanceof Error ? e.message : 'Failed to connect');
            setFlowState('error');
        }
    }, [startPolling, reconnectCredentialId]);

    // Auto-start on mount, or the moment autoStart flips true (an attached
    // credential turning disconnected → reconnect scan).
    useEffect(() => {
        if (autoStart && !startedRef.current) {
            startedRef.current = true;
            startQRFlow();
        }
    }, [autoStart, startQRFlow]);

    const pollStatus = async (connId: string) => {
        try {
            const response = await sendRef.current({
                event_name: 'whatsapp:qr:status',
                connection_id: connId,
            });

            if (!response?.success) {
                if (response?.status === 'error' || response?.error) {
                    stopPolling();
                    setError(response?.message || response?.error || 'Connection failed');
                    setFlowState('error');
                }
                return;
            }

            if (response.status === 'connected') {
                stopPolling();
                setPhoneNumber(response.phone_number || null);
                setFlowState('connected');
                invalidateCredentialsCache();
                onCredentialCreated(response.credential_id);
            } else if (response.qr_code) {
                setQrCode(response.qr_code);
            }
        } catch {
            // Silently retry on poll errors
        }
    };

    if (flowState === 'idle') {
        return (
            <button
                type="button"
                onClick={() => { startedRef.current = true; startQRFlow(); }}
                className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
                <Smartphone className="h-3.5 w-3.5" />
                {startLabel}
            </button>
        );
    }

    if (flowState === 'connected') {
        return (
            <div className="flex items-center gap-2 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                <Check className="w-4 h-4 text-emerald-600 dark:text-emerald-400 flex-shrink-0" />
                <div className="text-sm text-emerald-700 dark:text-emerald-300">
                    WhatsApp connected{phoneNumber ? ` (${phoneNumber})` : ''}
                </div>
            </div>
        );
    }

    if (flowState === 'scanning' && qrCode) {
        return (
            <div className="space-y-3 flex flex-col items-center">
                <div className="flex items-center gap-2 text-sm text-foreground/80">
                    <Smartphone className="w-4 h-4" />
                    <span>Scan with WhatsApp</span>
                </div>
                <div className="flex justify-center p-4 bg-white rounded-lg max-w-[240px] w-full">
                    <img
                        src={`data:image/png;base64,${qrCode}`}
                        alt="WhatsApp QR Code"
                        className="w-full h-auto"
                    />
                </div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground dark:text-zinc-500">
                    <Loader2 className="w-3 h-3 animate-spin" />
                    <span>Waiting for scan...</span>
                </div>
                <p className="text-[11px] text-muted-foreground/70 dark:text-zinc-600 text-center">
                    Open WhatsApp &rarr; Settings &rarr; Linked Devices &rarr; Link a Device
                </p>
                <p className="text-[11px] text-muted-foreground/70 dark:text-zinc-600">
                    $0.99/month connection fee applies.
                </p>
            </div>
        );
    }

    if (flowState === 'error') {
        return (
            <div className="max-w-md">
                {/* Retry lives INSIDE the banner — a subtle button below it was
                    easy to miss on an expired QR (the common case). */}
                <div className="flex items-center gap-2 p-2 pl-2.5 rounded-lg bg-red-500/10 border border-red-500/20">
                    <AlertCircle className="w-3.5 h-3.5 text-red-600 dark:text-red-400 flex-shrink-0" />
                    <div className="flex-1 text-xs text-red-600 dark:text-red-400">{error}</div>
                    <button
                        onClick={() => { startedRef.current = false; startQRFlow(); }}
                        className="flex items-center gap-1.5 shrink-0 rounded-md border border-red-500/30 px-2.5 py-1 text-xs font-medium text-red-600 dark:text-red-400 hover:bg-red-500/10 transition-colors"
                    >
                        <RefreshCw className="w-3 h-3" />
                        Retry
                    </button>
                </div>
            </div>
        );
    }

    // Loading state (shown briefly on mount while QR generates)
    return (
        <div className="flex items-center gap-2 py-4">
            <Loader2 className="w-4 h-4 text-muted-foreground dark:text-zinc-500 animate-spin" />
            <span className="text-sm text-muted-foreground dark:text-zinc-500">Loading QR code...</span>
        </div>
    );
};
