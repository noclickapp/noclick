/*
Server-side verification target for Supabase auth emails (confirm signup, password
recovery). The email templates (backend/scripts/generate_supabase_email_templates.py)
link here with ?token_hash=...&type=...; verifyOtp establishes the session with no
browser-bound state, so the link works from any browser or device. The previous
{{ .ConfirmationURL }} flow redirected through /auth/callback with a PKCE ?code=,
whose exchange needs the code-verifier cookie from the browser that initiated
signup — every cross-context open (in-app browser, phone-to-desktop, mail scanner)
failed with validation_failed (2026-07-16 incident).
*/
import { redirect, type LoaderFunctionArgs } from 'react-router';
import { createServerSupabaseClient } from '~/lib/supabase';
import { type EmailOtpType } from '@supabase/supabase-js';
import {
    getValidRedirectUrl,
    parseAuthCallbackError,
    resolveAuthCallbackErrorPath,
    authErrorPagePath,
    logSupabaseAuthError,
} from '~/lib/authCallbackErrors';

export async function loader({ request }: LoaderFunctionArgs) {
    const requestUrl = new URL(request.url);
    const token_hash = requestUrl.searchParams.get('token_hash');
    const type = requestUrl.searchParams.get('type') as EmailOtpType | null;
    const rawNext = requestUrl.searchParams.get('next');
    const next = getValidRedirectUrl(rawNext, requestUrl.origin);
    const headers = new Headers();

    // GoTrue-redirected failures (expired/consumed link) arrive as error query params.
    const authError = parseAuthCallbackError(requestUrl.searchParams);
    if (authError) {
        return redirect(
            resolveAuthCallbackErrorPath(authError, 'AuthConfirm', rawNext ? next : null),
            { headers },
        );
    }

    if (token_hash && type) {
        const supabase = createServerSupabaseClient(request, headers);

        const { error } = await supabase.auth.verifyOtp({
            type,
            token_hash,
        });

        if (!error) {
            return redirect(next, { headers });
        }
        logSupabaseAuthError('AuthConfirm', 'OTP verification failed', error, { type });
        return redirect(authErrorPagePath(error.code || 'otp_verification_failed'), { headers });
    }

    return redirect(authErrorPagePath('missing_token_hash'), { headers });
}
