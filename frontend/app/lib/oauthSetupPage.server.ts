// The page an OAuth popup shows when a provider has no app configured on this
// instance.
//
// Every authorize route used to `throw new Response('X OAuth not configured',
// { status: 500 })`, which surfaces in the popup as a bare error page: no cause,
// no fix, no next step. On a self-hosted install that is the normal state for
// every OAuth integration until the operator registers an app, so it is the
// first thing most self-hosters see.
//
// The instructions have to name BOTH processes. CLIENT_ID is read by the Remix
// routes AND the Python OAuth modules, CLIENT_SECRET only by the backend, and
// REDIRECT_URI only by the frontend — so "put the credentials in backend/.env"
// silently leaves the flow broken. Which vars go where comes from
// oauthProviderSetup, generated from the code that actually reads them.
//
// Styling is hand-written because this is a standalone document served from a
// route, outside the app bundle and its Tailwind build. It mirrors the app's
// dark tokens (tailwind.css `.dark`) and is dark-only, matching every route
// outside /dashboard.

import { providerSetup } from '~/lib/oauthProviderSetup';

const escapeHtml = (s: string) =>
    s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/**
 * The callback URL this instance expects for `provider`, derived from the
 * incoming request so it matches the host the user is actually on — a hardcoded
 * or env-pinned value is the usual cause of a redirect_uri mismatch later.
 */
export function callbackUrlFor(request: Request, provider: string): string {
    const url = new URL(request.url);
    const forwardedProto = request.headers.get('X-Forwarded-Proto');
    const proto = forwardedProto ? forwardedProto.split(',')[0].trim() : url.protocol.replace(':', '');
    const forwardedHost = request.headers.get('X-Forwarded-Host');
    const host = forwardedHost ? forwardedHost.split(',')[0].trim() : url.host;
    return `${proto}://${host}/api/auth/${provider}/callback`;
}

export interface OAuthNotConfiguredOptions {
    request: Request;
    provider: string;
    /** Env vars the calling route found missing; falls back to the generated map. */
    missing?: string[];
}

/** `VAR=value` lines, prefilling the redirect URI since we know it. */
function envBlock(vars: string[], callbackUrl: string): string {
    return vars.map((v) => (v.endsWith('REDIRECT_URI') ? `${v}=${callbackUrl}` : `${v}=`)).join('\n');
}

function fileBlock(title: string, note: string, vars: string[], callbackUrl: string, id: string): string {
    if (!vars.length) return '';
    return `
      <div class="file">
        <div class="file-head">
          <span class="path">${escapeHtml(title)}</span>
          <span class="note">${escapeHtml(note)}</span>
          <button type="button" class="copy" data-target="${id}">Copy</button>
        </div>
        <pre id="${id}">${escapeHtml(envBlock(vars, callbackUrl))}</pre>
      </div>`;
}

/**
 * A real page for the popup, not an error. Status is 200 deliberately: the
 * request succeeded, the instance simply has nothing configured, and a 5xx
 * renders as a browser error page in some popup contexts.
 */
export function oauthNotConfiguredResponse({
    request,
    provider,
    missing,
}: OAuthNotConfiguredOptions): Response {
    const setup = providerSetup(provider);
    const { label, consoleUrl } = setup;
    const callbackUrl = callbackUrlFor(request, provider);

    // The route knows what IT found missing; the map knows the other process's
    // half, which the route can't see.
    const frontendVars = setup.frontendEnv.length ? setup.frontendEnv : missing ?? [];
    const backendVars = setup.backendEnv;

    const html = `<!doctype html>
<html lang="en" class="dark"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="color-scheme" content="dark" />
<title>${escapeHtml(label)} isn't connected yet</title>
<style>
  :root {
    --background: hsl(0 0% 0%);
    --card: hsl(240 6% 10%);
    --popover: hsl(0 0% 10%);
    /* zinc-950: the app's panel surface. --card against a pure-black body is
       too big a step for a header strip — it reads as a light grey band. */
    --panel: hsl(240 10% 4%);
    --foreground: hsl(0 0% 98%);
    --muted-foreground: hsl(240 5% 64.9%);
    --border: hsl(240 3.7% 15.9%);
    --accent-fg: hsl(0 0% 98%);
  }
  * { box-sizing: border-box; }
  html, body { background: var(--background); }
  body {
    margin: 0; padding: 40px 24px 56px; color: var(--foreground);
    font: 14px/1.65 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  main { max-width: 600px; margin: 0 auto; }
  h1 { font-size: 20px; font-weight: 600; letter-spacing: -0.015em; margin: 0 0 8px; }
  .lead { color: var(--muted-foreground); margin: 0 0 32px; }
  ol { list-style: none; counter-reset: step; padding: 0; margin: 0; }
  li { counter-increment: step; position: relative; padding: 0 0 26px 40px; }
  li::before {
    content: counter(step);
    position: absolute; left: 0; top: -1px;
    width: 26px; height: 26px; border-radius: 999px;
    background: var(--panel); border: 1px solid var(--border);
    color: var(--muted-foreground);
    font-size: 12px; font-weight: 600;
    display: flex; align-items: center; justify-content: center;
  }
  /* connector between steps */
  li:not(:last-child)::after {
    content: ""; position: absolute; left: 13px; top: 30px; bottom: 4px;
    width: 1px; background: var(--border);
  }
  .step-title { font-weight: 500; margin-bottom: 10px; }
  code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12.5px;
         background: var(--card); border: 1px solid var(--border); border-radius: 5px; padding: 1px 5px; }
  pre {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12.5px;
    background: var(--background); color: var(--foreground);
    border: 0; border-radius: 0 0 9px 9px; margin: 0;
    padding: 11px 13px;
    /* Wrap rather than scroll: a prefilled REDIRECT_URI is longer than the
       popup is wide, and a horizontally scrolled line just looks truncated —
       you cannot tell there is more, and a popup is awkward to scroll. */
    white-space: pre-wrap; overflow-wrap: anywhere;
  }
  .file { border: 1px solid var(--border); border-radius: 10px; overflow: hidden;
          background: var(--background); margin-bottom: 10px; }
  .file-head { display: flex; align-items: center; gap: 10px;
               padding: 8px 10px 8px 13px; background: var(--panel);
               border-bottom: 1px solid var(--border); }
  .path { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
  .note { color: var(--muted-foreground); font-size: 12px; margin-right: auto; }
  /* One bordered container with the action inside, matching the env blocks —
     a separate stretched button reads as a slab next to the field. */
  .url-row { display: flex; align-items: center; border: 1px solid var(--border);
             border-radius: 10px; overflow: hidden; background: var(--background); }
  .url-row pre { flex: 1; min-width: 0; border: 0; border-radius: 0; padding: 10px 13px; }
  .url-row .copy { border: 0; border-left: 1px solid var(--border); border-radius: 0;
                   align-self: stretch; padding: 0 14px; background: var(--panel); }
  .url-row .copy:hover { background: var(--card); }
  button.copy {
    border: 1px solid var(--border); background: var(--panel); color: var(--foreground);
    border-radius: 7px; padding: 5px 11px; font-size: 12px; font-weight: 500; cursor: pointer;
    white-space: nowrap; transition: background 120ms ease, border-color 120ms ease;
    /* fixed width so swapping the label to "Copied" doesn't reflow the row */
    min-width: 62px; text-align: center;
  }
  button.copy:hover { background: var(--card); border-color: hsl(240 4% 26%); }
  a { color: var(--accent-fg); text-decoration: underline; text-underline-offset: 2px;
      text-decoration-color: hsl(240 4% 34%); }
  a:hover { text-decoration-color: currentColor; }
  footer { margin-top: 30px; padding-top: 18px; border-top: 1px solid var(--border);
           color: var(--muted-foreground); font-size: 13px; }
</style></head>
<body><main>
  <h1>${escapeHtml(label)} isn't connected yet</h1>
  <p class="lead">This instance has no ${escapeHtml(label)} OAuth app configured. Create one and give NoClick its credentials — it takes a minute.</p>
  <ol>
    <li>
      <div class="step-title">Create an OAuth app${consoleUrl ? '' : ` in ${escapeHtml(label)}'s developer settings`}</div>
      ${consoleUrl ? `<div><a href="${escapeHtml(consoleUrl)}" target="_blank" rel="noreferrer noopener">Open the ${escapeHtml(label)} developer console &rarr;</a></div>` : ''}
    </li>
    <li>
      <div class="step-title">Register this redirect URL on the app</div>
      <div class="url-row">
        <pre id="cb">${escapeHtml(callbackUrl)}</pre>
        <button type="button" class="copy" data-target="cb">Copy</button>
      </div>
    </li>
    <li>
      <div class="step-title">Give NoClick the credentials</div>
      <div class="note" style="margin-bottom:10px">
        Easiest: paste them into
        <a href="/dashboard?tab=settings&amp;section=oauth-apps" target="_blank" rel="noreferrer">Settings &rarr; OAuth Apps</a>.
        Saved there, they apply immediately — no restart. Or set them as
        environment variables, which take precedence:
      </div>
      ${fileBlock('frontend/.env', 'starts the sign-in', frontendVars, callbackUrl, 'fe')}
      ${fileBlock('backend/.env', 'exchanges the code for a token', backendVars, callbackUrl, 'be')}
      ${backendVars.length ? `<div class="note" style="margin-top:8px">The client ID goes in both; only the backend needs the secret. Restart both processes afterwards.</div>` : ''}
    </li>
    <li>
      <div class="step-title">Click Connect again</div>
    </li>
  </ol>
  <footer>You can close this window.</footer>
</main>
<script>
  document.querySelectorAll('button.copy').forEach(function (b) {
    b.addEventListener('click', function () {
      var el = document.getElementById(b.getAttribute('data-target'));
      navigator.clipboard.writeText((el && el.textContent) || '').then(function () {
        var prev = b.textContent; b.textContent = 'Copied';
        setTimeout(function () { b.textContent = prev; }, 1500);
      });
    });
  });
</script>
</body></html>`;

    return new Response(html, {
        status: 200,
        headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' },
    });
}
