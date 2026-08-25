/**
 * MCP OAuth consent page, at /mcp/consent — deliberately not /mcp/authorize,
 * which is the backend's own endpoint and the one advertised in the OAuth
 * metadata. It redirects here after validating the client and its registered
 * redirect URI, and on a single-origin installation the two paths would be the
 * same URL. Handles user authorization for MCP client connections.
 * Lives on the frontend (instead of backend) so the Supabase session cookie is available.
 *
 * Loopback redirects (CLI clients like Claude Code spin a short-lived
 * localhost callback server) are NOT 302'd blindly: the one-time auth code
 * would die in a browser error tab if the listener is gone.
 * Instead the action returns the callback URL and the page probes the
 * listener first, navigating only when something is actually listening and
 * showing recovery instructions when it isn't.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { LoaderFunctionArgs, ActionFunctionArgs, MetaFunction } from 'react-router';
import { redirect } from 'react-router';
import { json, type JsonPayloadOf } from '~/lib/routerResponse';
import { useActionData, useLoaderData } from 'react-router';
import { requireAuth } from '~/lib/supabase';
import { buildSeoMeta } from '~/lib/seo';
import { apiBaseUrl } from '~/lib/hostedDefaults';
import { useAnalytics } from '~/lib/analytics';
import { EVENTS } from '~/lib/analytics-events';

export const meta: MetaFunction = () =>
    buildSeoMeta({
        title: 'Authorize MCP Client - NoClick',
        description: 'Authorize an MCP client to access your NoClick workflows.',
        indexable: false,
    });

const SCOPE_DESCRIPTIONS: Record<string, { label: string; description: string }> = {
  'mcp:tools': {
    label: 'Workflow tools',
    description: 'Create, edit, and run workflows on your behalf',
  },
};

const DEFAULT_PERMISSIONS = [
  { label: 'Read workflows', description: 'View your existing workflows and their configurations' },
  { label: 'Modify workflows', description: 'Create, edit, and delete workflow nodes and connections' },
  { label: 'Execute workflows', description: 'Run workflows and view their output' },
  { label: 'Manage credentials', description: 'Assign saved credentials to workflow nodes' },
];

export async function loader({ request }: LoaderFunctionArgs) {
  const { session, headers } = await requireAuth(request);
  const url = new URL(request.url);

  return json(
    {
      accessToken: session.access_token,
      clientId: url.searchParams.get('client_id') || '',
      clientName: url.searchParams.get('client_name') || 'Unknown App',
      redirectUri: url.searchParams.get('redirect_uri') || '',
      state: url.searchParams.get('state') || '',
      codeChallenge: url.searchParams.get('code_challenge') || '',
      scope: url.searchParams.get('scope') || 'mcp:tools',
    },
    { headers }
  );
}

function isLoopbackUrl(url: string): boolean {
  try {
    const { hostname } = new URL(url);
    return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]';
  } catch {
    return false;
  }
}

export async function action({ request }: ActionFunctionArgs) {
  const formData = await request.formData();
  const backendUrl = process.env.VITE_API_URL || apiBaseUrl();

  // Forward consent server-side so the browser never depends on cross-origin proxy behavior.
  const params = new URLSearchParams();
  for (const [key, value] of formData.entries()) {
    params.append(key, value as string);
  }

  const response = await fetch(`${backendUrl}/mcp/authorize/consent`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: params.toString(),
  });

  const data = await response.json();

  if (data.redirect_url) {
    // Approved loopback callbacks carry a one-time code to a listener that may
    // have died — hand the URL to the page so it can probe before navigating.
    if (formData.get('action') === 'approve' && isLoopbackUrl(data.redirect_url)) {
      return json({ callbackUrl: data.redirect_url as string });
    }
    return redirect(data.redirect_url);
  }

  throw new Response(data.error || 'Consent failed', { status: response.status });
}

/**
 * Post-consent delivery for loopback callbacks: probe the CLI's localhost
 * listener (no-cors fetch to the ORIGIN, never the callback path — a probe
 * must not consume the one-time code), navigate when it answers, and show
 * recovery steps when nothing is listening.
 */
function LoopbackCallbackDelivery({ callbackUrl, clientName }: { callbackUrl: string; clientName: string }) {
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

export default function McpAuthorize() {
  const {
    accessToken,
    clientId,
    clientName,
    redirectUri,
    state,
    codeChallenge,
    scope,
  } = useLoaderData() as JsonPayloadOf<typeof loader>;
  const actionData = useActionData() as JsonPayloadOf<typeof action>;

  const scopes = scope.split(' ');
  const permissions = scopes.flatMap((s) => {
    const desc = SCOPE_DESCRIPTIONS[s];
    return desc ? [desc] : [];
  });
  const displayPermissions = permissions.length > 0 ? permissions : DEFAULT_PERMISSIONS;

  return (
    <div className="min-h-screen flex items-center justify-center bg-background dark:bg-zinc-950 px-5 py-10 font-sans antialiased">
      <div className="w-full max-w-[400px] rounded-2xl border border-border bg-sunken p-8">
        {/* Logo */}
        <div className="flex items-center justify-center gap-2.5 mb-8">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 499 499"
            fill="none"
            className="w-7 h-7"
          >
            <path
              fillRule="evenodd"
              clipRule="evenodd"
              d="M4.364 1.16509C3.189 1.73709 1.727 3.30409 1.114 4.64909C0.308 6.41909 0 59.9921 0 198.624C0 390.154 0 390.154 3.046 393.2C9.504 399.658 4.522 403.973 94.475 314.025C175.509 232.996 175.509 232.996 204.493 261.993C233.477 290.99 233.477 290.99 162.871 361.745C102.884 421.858 91.862 433.343 89.586 438.106C78.436 461.434 90.073 488.305 114.86 496.469C123.494 499.312 135.857 498.314 144.627 494.067C151.009 490.975 156.536 485.712 222.013 420.379C292.525 350.02 292.525 350.02 361.013 418.533C398.681 456.214 431.171 488.21 433.214 489.634C439.38 493.931 449.244 497 456.889 497C487.231 497 506.795 466.17 494.427 437.846C491.837 431.914 487.084 426.915 421.598 361.247C351.54 290.994 351.54 290.994 420.637 221.747C495.936 146.285 493.567 149.014 496.126 134.785C499.652 115.168 487.889 95.7401 468.357 88.9211C459.622 85.8721 446.797 86.5141 438 90.4421C431.915 93.1591 427.065 97.7661 361.985 162.664C292.47 231.983 292.47 231.983 263.493 202.993C234.515 174.002 234.515 174.002 314.757 93.7361C403.441 5.02709 398.137 11.1831 392.11 3.96209C389.219 0.500089 389.219 0.500089 197.86 0.314089C67.242 0.186089 5.822 0.457089 4.364 1.16509Z"
              fill="hsl(var(--foreground))"
            />
          </svg>
          <span className="text-[22px] font-bold text-foreground tracking-tight">NoClick</span>
        </div>

        {actionData?.callbackUrl ? (
          <LoopbackCallbackDelivery callbackUrl={actionData.callbackUrl} clientName={clientName} />
        ) : (
        <>
        {/* Title */}
        <h1 className="text-lg font-medium text-foreground text-center mb-1.5 tracking-tight">
          <span className="font-semibold">{clientName}</span> wants to connect
        </h1>
        <p className="text-muted-foreground/70 dark:text-zinc-500 text-center mb-6 text-[13px] leading-relaxed">
          This will allow access to your NoClick workspace
        </p>

        {/* Permissions */}
        <div className="rounded-xl border border-border bg-card/60 p-4 mb-6">
          <div className="text-[10px] font-semibold text-muted-foreground/60 dark:text-zinc-600 uppercase tracking-widest mb-3">
            This app will be able to
          </div>
          <ul className="space-y-3">
            {displayPermissions.map((perm) => (
              <li key={perm.label} className="flex items-start gap-2.5">
                <span className="mt-0.5 flex-shrink-0 w-[18px] h-[18px] rounded-full bg-emerald-500/15 flex items-center justify-center">
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 16 16"
                    fill="currentColor"
                    className="w-2.5 h-2.5 text-emerald-600 dark:text-emerald-400"
                  >
                    <path d="M12.207 4.793a1 1 0 010 1.414l-5 5a1 1 0 01-1.414 0l-2-2a1 1 0 011.414-1.414L6.5 9.086l4.293-4.293a1 1 0 011.414 0z" />
                  </svg>
                </span>
                <div className="min-w-0">
                  <div className="text-[13px] text-foreground font-medium leading-tight">{perm.label}</div>
                  <div className="text-[11px] text-muted-foreground/60 dark:text-zinc-600 leading-snug mt-0.5">{perm.description}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>

        {/* Form POSTs to this route's action, which forwards to backend server-side */}
        <form method="POST">
          <input type="hidden" name="client_id" value={clientId} />
          <input type="hidden" name="redirect_uri" value={redirectUri} />
          <input type="hidden" name="state" value={state} />
          <input type="hidden" name="code_challenge" value={codeChallenge} />
          <input type="hidden" name="scope" value={scope} />
          <input type="hidden" name="access_token" value={accessToken} />

          <div className="flex gap-2.5">
            <button
              type="submit"
              name="action"
              value="deny"
              className="flex-1 py-2.5 px-4 rounded-lg text-[13px] font-medium cursor-pointer bg-transparent text-muted-foreground dark:text-zinc-500 border border-border hover:bg-accent dark:hover:bg-zinc-900 hover:text-foreground hover:border-foreground/20 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              name="action"
              value="approve"
              className="flex-1 py-2.5 px-4 rounded-lg text-[13px] font-medium cursor-pointer bg-primary text-primary-foreground border-none hover:bg-primary/90 transition-colors"
            >
              Allow access
            </button>
          </div>
        </form>

        {/* Redirect info */}
        <div className="mt-5 pt-3.5 border-t border-border dark:border-zinc-900 text-[10px] text-muted-foreground/50 dark:text-zinc-700 text-center break-all">
          Redirecting to {redirectUri}
        </div>
        </>
        )}
      </div>
    </div>
  );
}
