// EmailTriggerField — editable widget for the inbound-email trigger node (ui:widget="email_trigger").
// The user picks an inbox local-part: it is persisted to config (the node's only required field) on
// every keystroke, then the address is auto-reserved via the
// email:reserve_address socket event. Reservation is a pure side-effect — it is NOT written back to
// config (the inbound route resolves by local_part, keyed on workflow+node), which avoids clobbering
// the local_part write. The reserved address is derived for display.

import { useCallback, useEffect, useRef, useState } from 'react';
import { Loader2, Check, X } from 'lucide-react';
import { CopyButton } from '~/components/ui/CopyButton';
import { sendEventAsync } from '~/lib/socket-sender';
import { inboundEmailDomain } from '~/lib/inboundEmail';
import type { WidgetRenderProps } from './schemaWidgetRegistry';

// Display-only suffix; the backend is the source of truth. The community build
// leaves this empty until the operator wires an inbound provider.
export const EMAIL_DOMAIN = inboundEmailDomain() || '';

type Status = 'idle' | 'checking' | 'reserving' | 'reserved' | 'taken' | 'invalid' | 'error';

const inputClasses =
  'w-full pl-3 pr-32 py-2 rounded-lg border border-border dark:border-white/[0.08] bg-foreground/[0.03] text-foreground text-sm outline-none placeholder:text-[hsl(var(--placeholder))] focus:border-foreground/20 focus:bg-foreground/[0.05]';

interface CheckResult {
  available: boolean;
  error?: string;
}

interface ReserveResult {
  success: boolean;
  error?: string;
}

// email:* events are handled as raw dicts on the backend (not in the generated
// event types), so widen the request shape for sendEventAsync without `any`.
type SocketRequest = Parameters<typeof sendEventAsync>[0];

export function EmailTriggerField({ fieldKey, value, onChange, nodeId, workflowId }: WidgetRenderProps) {
  const [local, setLocal] = useState<string>((value as string) || '');
  // A saved local_part means the node was reserved before; show it as reserved optimistically.
  const [status, setStatus] = useState<Status>(value ? 'reserved' : 'idle');
  const [message, setMessage] = useState<string>('');
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Re-sync local state when the selected node changes.
  useEffect(() => {
    setLocal((value as string) || '');
    setStatus(value ? 'reserved' : 'idle');
    setMessage('');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodeId]);

  useEffect(() => () => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
  }, []);

  // Check availability and, if free, reserve the address. Pure side-effect — the reservation row is
  // keyed by (workflow_id, node_id) on the backend; nothing is written back to config here.
  const checkAndReserve = useCallback(
    async (lp: string) => {
      if (!lp || !workflowId || !nodeId) {
        setStatus('idle');
        return;
      }
      setStatus('checking');
      try {
        const chk = (await sendEventAsync({
          event_name: 'email:check_local_part',
          local_part: lp,
          workflow_id: workflowId,
          node_id: nodeId,
        } as unknown as SocketRequest)) as CheckResult;
        if (chk?.error) {
          setStatus('invalid');
          setMessage(chk.error);
          return;
        }
        if (!chk?.available) {
          setStatus('taken');
          setMessage('That address is already taken');
          return;
        }

        setStatus('reserving');
        const res = (await sendEventAsync({
          event_name: 'email:reserve_address',
          local_part: lp,
          workflow_id: workflowId,
          node_id: nodeId,
        } as unknown as SocketRequest)) as ReserveResult;
        if (res?.success) {
          setStatus('reserved');
          setMessage('');
        } else {
          setStatus('taken');
          setMessage(res?.error || 'Could not reserve this address');
        }
      } catch {
        setStatus('error');
        setMessage('Could not reach the server');
      }
    },
    [nodeId, workflowId],
  );

  const onInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const lp = e.target.value.toLowerCase().trim();
    setLocal(lp);
    setMessage('');
    // The ONLY config write: persist local_part so the field saves and the required-field check clears.
    onChange(fieldKey, lp);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!lp) {
      setStatus('idle');
      return;
    }
    setStatus('checking');
    debounceRef.current = setTimeout(() => checkAndReserve(lp), 450);
  };

  const fullAddress = local ? `${local}@${EMAIL_DOMAIN}` : '';

  if (!EMAIL_DOMAIN) {
    return (
      <div className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
        Inbound email is disabled. Set <code>INBOUND_EMAIL_DOMAIN</code> on the backend and{' '}
        <code>VITE_INBOUND_EMAIL_DOMAIN</code> when building the frontend after your mail provider forwards to{' '}
        <code>/email/inbound</code>.
      </div>
    );
  }

  return (
    <div>
      <div className="relative">
        <input
          type="text"
          value={local}
          onChange={onInput}
          placeholder="inbox-name"
          spellCheck={false}
          autoCapitalize="none"
          className={inputClasses}
        />
        <span className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground/70 dark:text-white/40 text-sm pointer-events-none">
          @{EMAIL_DOMAIN}
        </span>
      </div>

      <div className="mt-1.5 min-h-[20px] text-xs">
        {status === 'checking' && (
          <span className="flex items-center gap-1.5 text-muted-foreground/70 dark:text-white/40">
            <Loader2 className="w-3 h-3 animate-spin" /> Checking availability…
          </span>
        )}
        {status === 'reserving' && (
          <span className="flex items-center gap-1.5 text-muted-foreground/70 dark:text-white/40">
            <Loader2 className="w-3 h-3 animate-spin" /> Reserving…
          </span>
        )}
        {status === 'reserved' && (
          <span className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400">
            <Check className="w-3 h-3" />
            <span className="text-muted-foreground dark:text-white/70">Active</span>
            <code className="text-foreground/90">{fullAddress}</code>
            <CopyButton value={fullAddress} />
          </span>
        )}
        {(status === 'taken' || status === 'invalid' || status === 'error') && (
          <span className="flex items-center gap-1.5 text-red-600 dark:text-red-400">
            <X className="w-3 h-3" /> {message}
          </span>
        )}
      </div>
    </div>
  );
}
