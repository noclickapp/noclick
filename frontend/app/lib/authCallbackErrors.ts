// Shared handling for Supabase auth-callback errors across /auth/callback, /auth/confirm and
// /auth/reset-password. When verification fails upstream, Supabase redirects back with
// error/error_code/error_description (in query and/or hash) instead of a code; these helpers
// classify the failure and build the redirect target so all three routes stay in lockstep.
// Also owns post-auth redirect validation (getValidRedirectUrl) for the same routes.

// Validate a ?next= redirect target to prevent open redirects: relative paths and
// same-origin URLs pass through; localhost is allowed for dev (backend on another port);
// anything else falls back to /dashboard.
export function getValidRedirectUrl(nextUrl: string | null, origin: string): string {
    if (!nextUrl) return '/dashboard';

    try {
        // Decode if URL-encoded
        const decoded = decodeURIComponent(nextUrl);

        // Check if it's a relative path
        if (decoded.startsWith('/') && !decoded.startsWith('//')) {
            return decoded;
        }

        // Parse as absolute URL
        const parsed = new URL(decoded);

        // Allow same origin
        if (parsed.origin === origin) {
            return decoded;
        }

        // Allow localhost URLs (for local dev with backend on different port)
        if (parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1') {
            return decoded;
        }

        // Disallow other external URLs
        return '/dashboard';
    } catch {
        return '/dashboard';
    }
}

export interface AuthCallbackError {
    error: string;
    errorCode: string | null;
    errorDescription: string | null;
}

// Works for both query strings and URL fragments (pass `new URLSearchParams(hash.slice(1))`).
export function parseAuthCallbackError(params: URLSearchParams): AuthCallbackError | null {
    const error = params.get('error');
    if (!error) return null;
    return {
        error,
        errorCode: params.get('error_code'),
        errorDescription: params.get('error_description'),
    };
}

// A bare access_denied (no error_code) is a denial at the provider's door — the user pressing
// cancel on the consent screen, or the provider refusing entry (org policy, unverified app).
// GoTrue-originated denials (otp_expired, signup_disabled, user_banned, ...) always carry an
// error_code, so they never land here.
export function isOAuthUserCancellation(err: AuthCallbackError): boolean {
    return err.error === 'access_denied' && !err.errorCode;
}

// The reason rides the URL so the error page can show accurate copy and report it to analytics.
export function authErrorPagePath(reason: string): string {
    return `/auth/auth-code-error?reason=${encodeURIComponent(reason)}`;
}

export function loginCancelledPath(next: string | null): string {
    return `/auth/login?notice=oauth_cancelled${next ? `&next=${encodeURIComponent(next)}` : ''}`;
}

export function authCallbackErrorReason(err: AuthCallbackError): string {
    return err.errorCode || err.error;
}

// One decision tree for provider-returned errors, shared by the server loader and the
// client fragment handler: cancellations go back to login with a notice, everything else
// to the error page. `validatedNext` must already be open-redirect-safe.
export function resolveAuthCallbackErrorPath(
    err: AuthCallbackError,
    context: string,
    validatedNext: string | null,
): string {
    if (isOAuthUserCancellation(err)) {
        console.log(`[${context}] OAuth flow cancelled/denied at provider`, {
            description: err.errorDescription || '',
        });
        return loginCancelledPath(validatedNext);
    }
    console.error(`[${context}] Auth provider returned error:`, err);
    return authErrorPagePath(authCallbackErrorReason(err));
}

// One log shape for Supabase SDK failures (exchangeCodeForSession/verifyOtp/setSession) so
// production logs stay greppable and consistent across the auth routes.
export function logSupabaseAuthError(
    context: string,
    action: string,
    error: { code?: string; status?: number; message: string },
    extra?: Record<string, unknown>,
): void {
    console.error(`[${context}] ${action}:`, {
        code: error.code,
        status: error.status,
        message: error.message,
        ...extra,
    });
}
