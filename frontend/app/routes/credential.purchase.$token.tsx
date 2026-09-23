// Phone-number purchase links require the account owner's signed-in session.
// This page reuses the credential purchase form, with a server-quoted review step
// and authenticated, CSRF-protected actions before any credits are spent.
import { useCallback, useRef, useState } from 'react';
import { Link, useLoaderData, type ActionFunctionArgs, type LoaderFunctionArgs } from 'react-router';
import { ArrowLeft, Check, Clock3, Phone, ShieldCheck } from 'lucide-react';
import { json, type JsonPayloadOf } from '~/lib/routerResponse';
import { requireAuth } from '~/lib/supabase';
import { apiBaseUrl } from '~/lib/hostedDefaults';
import { csrfFailureResponse, generateCsrfToken } from '~/lib/csrf.server';
import { Button } from '~/components/ui/button';
import { PhoneNumberPurchaseForm, type PhonePurchaseQuote } from '~/components/credential/PhoneNumberPurchaseForm';
import { formatPhoneForDisplay } from '~/lib/phoneFormat';
import type { OAuthExchange } from '~/hooks/oauth/OAuthExchangeContext';

interface PurchaseState {
    status: string;
    purpose?: string | null;
    phone_number?: string | null;
    credential_id?: string | null;
    error?: string | null;
    quote?: PhonePurchaseQuote | null;
}

function returnPath(request: Request) {
    const wanted = new URL(request.url).searchParams.get('return_to') || '';
    // Only the existing builder/provide flows may receive a purchase return.
    return /^\/(?:b|credential\/provide)\/[a-zA-Z0-9-]+$/.test(wanted)
        ? wanted : '/dashboard?tab=dashboard';
}

async function backend(token: string, accessToken: string, operation?: string, body?: unknown) {
    const res = await fetch(`${apiBaseUrl()}/api/credential-request/${encodeURIComponent(token)}/phone${operation ? `/${operation}` : ''}`, {
        method: operation ? 'POST' : 'GET',
        headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
        ...(operation ? { body: JSON.stringify(body) } : {}),
        signal: AbortSignal.timeout(90_000),
    });
    const data = await res.json();
    if (!res.ok) {
        const detail = data.detail;
        return { error: typeof detail === 'string' ? detail : detail?.error || 'Could not complete this request.', kind: detail?.kind };
    }
    return data;
}

export async function loader({ request, params }: LoaderFunctionArgs) {
    const { session, user, headers } = await requireAuth(request);
    const { token: csrfToken, cookieHeader } = await generateCsrfToken(request);
    headers.append('Set-Cookie', cookieHeader);
    headers.set('Cache-Control', 'private, no-store');
    headers.set('Referrer-Policy', 'no-referrer');
    const result = await backend(params.token!, session!.access_token) as PurchaseState;
    return json({ purchase: result, csrfToken, returnTo: returnPath(request), email: user.email }, { headers });
}

export async function action({ request, params }: ActionFunctionArgs) {
    const { session, headers } = await requireAuth(request);
    const form = await request.formData();
    const csrfFailure = await csrfFailureResponse(request, form);
    if (csrfFailure) {
        // Keep any rotated auth cookies even when CSRF needs refreshing.
        for (const cookie of headers.getSetCookie()) csrfFailure.headers.append('Set-Cookie', cookie);
        return csrfFailure;
    }
    headers.set('Cache-Control', 'private, no-store');
    const operation = String(form.get('operation'));
    if (!['search', 'quote', 'confirm', 'status'].includes(operation)) return json({ error: 'Unknown action.' }, { status: 400, headers });
    let body: unknown;
    try { body = JSON.parse(String(form.get('payload') || '{}')); }
    catch { return json({ error: 'Invalid request.' }, { status: 400, headers }); }
    return json(await backend(params.token!, session!.access_token, operation === 'status' ? undefined : operation, body), { headers });
}

export default function PhonePurchasePage() {
    const { purchase, csrfToken, returnTo, email } = useLoaderData<JsonPayloadOf<typeof loader>>();
    const [state, setState] = useState<PurchaseState>(purchase);
    const csrf = useRef(csrfToken);
    const [checking, setChecking] = useState(false);
    const send = useCallback<OAuthExchange>(async (event) => {
        const { event_name, ...payload } = event;
        const form = new FormData();
        form.set('csrf_token', csrf.current);
        form.set('operation', event_name.replace('phone_number:', ''));
        form.set('payload', JSON.stringify(payload));
        const response = await fetch(window.location.href, { method: 'POST', body: form });
        // A session expiring mid-purchase must be recovered through sign-in,
        // never interpreted as a successful HTML action response.
        if (response.redirected) throw new Error('Sign in again and check the purchase status.');
        const data = await response.json();
        if (data.csrfToken) csrf.current = data.csrfToken;
        return data;
    }, []);
    const check = async () => {
        setChecking(true);
        try {
            const next = await send({ event_name: 'phone_number:status' });
            setState(s => next.status ? next : { ...s, error: next.error || 'Could not check this request. Try again.' });
        }
        catch { setState(s => ({ ...s, error: 'Could not check this request. Refresh the page to sign in again.' })); }
        finally { setChecking(false); }
    };
    const completed = state.status === 'fulfilled';
    const waiting = state.status === 'provisioning';
    return (
        <main className="min-h-screen bg-background px-5 py-12 text-foreground sm:py-20">
            <div className="mx-auto max-w-xl">
                <Link to={returnTo} className="mb-10 inline-flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"><ArrowLeft className="h-4 w-4" />Back to setup</Link>
                <div className="mb-8 flex h-11 w-11 items-center justify-center rounded-2xl bg-foreground/[0.05]">
                    {completed ? <Check className="h-5 w-5" /> : waiting ? <Clock3 className="h-5 w-5" /> : <Phone className="h-5 w-5" />}
                </div>
                <h1 className="text-3xl font-semibold tracking-tight">{completed ? 'Your number is ready' : waiting ? 'Checking your purchase' : 'A number for your agent'}</h1>
                <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{purchase.purpose || 'Choose a phone number for your account. Connect it to an agent when you’re ready.'}</p>
                <div className="mb-8 mt-4 flex items-center gap-2 text-xs text-muted-foreground"><ShieldCheck className="h-3.5 w-3.5 shrink-0" />Signed in as {email}</div>
                {state.status === 'pending' ? (
                    <PhoneNumberPurchaseForm
                        key={state.quote?.id || 'selection'}
                        sendEvent={send}
                        confirmation={{ initialQuote: state.quote, onState: next => setState(s => ({ ...s, ...next })) }}
                        onCredentialCreated={(credential_id, phone_number) => setState(s => ({ ...s, status: 'fulfilled', credential_id, phone_number, error: null }))}
                    />
                ) : (
                    <div className="space-y-5 rounded-2xl bg-foreground/[0.035] p-6">
                        {completed ? <>
                            <p className="text-2xl font-medium tracking-tight">{state.phone_number ? formatPhoneForDisplay(state.phone_number) : 'Phone number purchased'}</p>
                            <p className="text-sm leading-relaxed text-muted-foreground">Saved to your credentials. Continue setup to connect it to your agent.</p>
                            <Button asChild><Link to={returnTo}>Continue setup</Link></Button>
                        </> : <>
                            <p className="text-sm leading-relaxed text-muted-foreground">{state.error || (waiting ? 'Your purchase is being processed. You can safely check its status here.' : `This request is ${state.status || 'unavailable'}. Ask for a new link or sign in with the account that requested it.`)}</p>
                            {waiting && <Button variant="secondary" disabled={checking} onClick={() => void check()}>{checking ? 'Checking…' : 'Check status'}</Button>}
                        </>}
                    </div>
                )}
            </div>
        </main>
    );
}
