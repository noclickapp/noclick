// Phone-number purchase links require the account owner's signed-in session.
// This page reuses the credential purchase form, with a server-quoted review step
// and authenticated, CSRF-protected actions (credential.purchase.$token.action)
// before any credits are spent.
import { useState } from 'react';
import { Link, useLoaderData, useParams, type LoaderFunctionArgs } from 'react-router';
import { ArrowLeft, Check, Clock3, Phone, ShieldCheck } from 'lucide-react';
import { json, type JsonPayloadOf } from '~/lib/routerResponse';
import { requireAuth } from '~/lib/supabase';
import { generateCsrfToken } from '~/lib/csrf.server';
import { phonePurchaseBackend } from '~/lib/phonePurchase.server';
import { Button } from '~/components/ui/button';
import { OrderReview, PhoneNumberPurchaseForm, type PhonePurchaseQuote } from '~/components/credential/PhoneNumberPurchaseForm';
import { formatPhoneForDisplay } from '~/lib/phoneFormat';
import { usePurchaseLinkTransport, type NumberOrder } from '~/hooks/usePhoneNumberPurchase';

interface PurchaseState {
    status: string;
    purpose?: string | null;
    phone_number?: string | null;
    credential_id?: string | null;
    error?: string | null;
    quote?: PhonePurchaseQuote | null;
    /** While the carrier reviews the number's documents (status in_review or rejected). */
    order?: NumberOrder | null;
}

function returnPath(request: Request) {
    const wanted = new URL(request.url).searchParams.get('return_to') || '';
    // Only the existing builder/provide flows may receive a purchase return.
    return /^\/(?:b|credential\/provide)\/[a-zA-Z0-9-]+$/.test(wanted)
        ? wanted : '/dashboard?tab=dashboard';
}

export async function loader({ request, params }: LoaderFunctionArgs) {
    const { backendHeaders, user, headers } = await requireAuth(request);
    const { token: csrfToken, cookieHeader } = await generateCsrfToken(request);
    headers.append('Set-Cookie', cookieHeader);
    headers.set('Cache-Control', 'private, no-store');
    headers.set('Referrer-Policy', 'no-referrer');
    const result = await phonePurchaseBackend<PurchaseState>(params.token!, backendHeaders);
    return json({ purchase: result, csrfToken, returnTo: returnPath(request), signedInAs: user.email || (user.phone ? formatPhoneForDisplay(user.phone) : 'your account') }, { headers });
}

export default function PhonePurchasePage() {
    const { purchase, csrfToken, returnTo, signedInAs } = useLoaderData<JsonPayloadOf<typeof loader>>();
    const [state, setState] = useState<PurchaseState>(purchase);
    const [checking, setChecking] = useState(false);
    const { token } = useParams();
    const send = usePurchaseLinkTransport(token!, csrfToken);
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
    const reviewing = (state.status === 'in_review' || state.status === 'rejected') && state.order;
    return (
        <main className="min-h-screen bg-background px-5 py-12 text-foreground sm:py-20">
            <div className="mx-auto max-w-xl">
                <Link to={returnTo} className="mb-10 inline-flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"><ArrowLeft className="h-4 w-4" />Back to setup</Link>
                <div className="mb-8 flex h-11 w-11 items-center justify-center rounded-2xl bg-foreground/[0.05]">
                    {completed ? <Check className="h-5 w-5" /> : waiting || reviewing ? <Clock3 className="h-5 w-5" /> : <Phone className="h-5 w-5" />}
                </div>
                <h1 className="text-3xl font-semibold tracking-tight">
                    {completed
                        ? 'Your number is ready'
                        : state.status === 'rejected'
                          ? 'The carrier needs changes'
                          : reviewing
                            ? 'In the carrier’s review'
                            : waiting
                              ? 'Checking your purchase'
                              : 'A number for your agent'}
                </h1>
                <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{purchase.purpose || 'Choose a phone number for your account. Connect it to an agent when you’re ready.'}</p>
                <div className="mb-8 mt-4 flex items-center gap-2 text-xs text-muted-foreground"><ShieldCheck className="h-3.5 w-3.5 shrink-0" />Signed in as {signedInAs}</div>
                {reviewing && state.order ? (
                    <OrderReview order={state.order} sendEvent={send} onState={(next) => setState((s) => ({ ...s, ...next }))} />
                ) : state.status === 'pending' ? (
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
