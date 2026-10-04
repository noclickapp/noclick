/**
 * Post-consent delivery for MCP clients whose OAuth callback is a loopback
 * listener (CLI clients like Claude Code spin a short-lived localhost server).
 * Shared by every MCP consent page: the one-time code would die in a browser
 * error tab if the listener is gone (the #1 observed MCP-connect failure,
 * ERR_CONNECTION_REFUSED, 2026-07-08), so the page probes the listener first,
 * navigating only when something is listening and showing recovery steps when
 * it isn't.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useAnalytics } from '~/lib/analytics';
import { EVENTS } from '~/lib/analytics-events';

export function isLoopbackUrl(url: string): boolean {
  try {
    const { hostname } = new URL(url);
    return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]';
  } catch {
    return false;
  }
}

/**
 * Probe the CLI's localhost listener (no-cors fetch to the ORIGIN, never the
 * callback path — a probe must not consume the one-time code), navigate when
 * it answers, and show recovery steps when nothing is listening.
 */
export function LoopbackCallbackDelivery({ callbackUrl, clientName }: { callbackUrl: string; clientName: string }) {
  const [phase, setPhase] = useState<'probing' | 'unreachable'>('probing');
  const [copied, setCopied] = useState(false);
  const probing = useRef(false);
  const { logActivity } = useAnalytics();

  const probeAndDeliver = useCallback(async () => {
    if (probing.current) return;
    probing.current = true;
    setPhase('probing');
    const origin = new URL(callbackUrl).origin;
    try {
      // Opaque response (even a 404) proves a listener; connection refused rejects.
      await fetch(`${origin}/`, { mode: 'no-cors', signal: AbortSignal.timeout(2500) });
      window.location.replace(callbackUrl);
    } catch {
      logActivity(EVENTS.MCP_CALLBACK_UNREACHABLE, {
        client_name: clientName,
        callback_origin: origin,
      });
      setPhase('unreachable');
    } finally {
      probing.current = false;
    }
  }, [callbackUrl, clientName, logActivity]);

  useEffect(() => {
    probeAndDeliver();
  }, [probeAndDeliver]);

  if (phase === 'probing') {
    return (
      <div className="text-center space-y-3 py-6">
        <div className="text-sm text-muted-foreground dark:text-zinc-300">Access granted</div>
        <p className="text-[13px] text-muted-foreground/70 dark:text-zinc-500">
          Handing the authorization back to <span className="text-muted-foreground dark:text-zinc-300">{clientName}</span>…
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-sm font-medium text-foreground mb-1">
          Access granted — but your terminal isn&apos;t listening
        </h2>
        <p className="text-[12px] text-muted-foreground/70 dark:text-zinc-500 leading-relaxed">
          <span className="text-muted-foreground">{clientName}</span> started this authorization from a
          temporary local server on your machine, and that server is no longer reachable. This
          usually means the terminal session was closed, timed out, or this link was opened from
          an earlier attempt.
        </p>
      </div>

      <ol className="text-[12px] text-muted-foreground space-y-1.5 list-decimal list-inside">
        <li>Keep the terminal session with {clientName} open — don&apos;t close or interrupt it.</li>
        <li>
          Re-run the authentication there (in Claude Code: <code className="text-foreground bg-muted dark:bg-zinc-900 px-1 rounded">/mcp</code> →
          select the server → <span className="text-foreground">Authenticate</span>).
        </li>
        <li>Approve promptly in the browser tab it opens — each attempt mints a fresh link.</li>
      </ol>

      <div className="flex gap-2.5">
        <button
          onClick={probeAndDeliver}
          className="flex-1 py-2.5 px-4 rounded-lg text-[13px] font-medium cursor-pointer bg-primary text-primary-foreground border-none hover:bg-primary/90 transition-colors"
        >
          Try again
        </button>
        <button
          onClick={() => {
            navigator.clipboard.writeText(callbackUrl).then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 2000);
            });
          }}
          className="flex-1 py-2.5 px-4 rounded-lg text-[13px] font-medium cursor-pointer bg-transparent text-muted-foreground border border-border hover:bg-accent dark:hover:bg-zinc-900 hover:text-foreground transition-colors"
        >
          {copied ? 'Copied' : 'Copy callback URL'}
        </button>
      </div>

      <p className="text-[11px] text-muted-foreground/60 dark:text-zinc-600 leading-relaxed">
        Running {clientName} over SSH or in a container? The callback points at that machine&apos;s
        localhost — copy the URL above and open it from there (e.g.{' '}
        <code className="text-muted-foreground/70 dark:text-zinc-500">curl &apos;&lt;url&gt;&apos;</code>), or see the{' '}
        <a
          href="https://docs.noclick.com/mcp/setup"
          target="_blank"
          rel="noopener noreferrer"
          className="text-muted-foreground/70 dark:text-zinc-500 underline hover:text-muted-foreground"
        >
          setup guide
        </a>
        .
      </p>

      {/* Escape hatch: navigation to localhost is never blocked even where the
          probe fetch is (older mixed-content rules), so a false-negative probe
          can't strand a user whose listener is actually alive. */}
      <button
        onClick={() => window.location.replace(callbackUrl)}
        className="w-full text-[11px] text-muted-foreground/60 dark:text-zinc-600 hover:text-muted-foreground underline transition-colors"
      >
        Terminal is running? Open the callback link directly
      </button>
    </div>
  );
}
