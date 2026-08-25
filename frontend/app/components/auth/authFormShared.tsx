// Shared building blocks for the sign-in and sign-up pages so the two can't drift:
// the Google OAuth button (Remix Form + in-flight spinner), the small button
// spinner. Extracted when signup gained Google + the agent-scaffold treatment
// that login already had. The button self-detects its pending state via useNavigation.

import { Form, useNavigation } from 'react-router';
import { Button } from '~/components/ui/button';
import { AUTH_GOOGLE_BUTTON_CLASS } from '~/components/auth/AuthShell';

/** Absolute leading-spinner placement for a center-labelled button. Centers with
    inset+auto-margins, never `-translate-y-1/2`: `animate-spin`'s keyframe sets
    `transform: rotate(...)`, which replaces any translate and drops the spinner
    half its height below center. */
export const LEADING_SPINNER_CLASS = 'absolute inset-y-0 left-4 my-auto';

/** Small in-button loading spinner (inherits the button's text color). */
export function ButtonSpinner({ className }: { className?: string }) {
    return (
        <span
            className={`h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent ${className ?? ''}`}
        />
    );
}

export function GoogleIcon() {
    return (
        <svg
            viewBox="0 0 24 24"
            width="20"
            height="20"
            className="rr-block ph-no-capture"
        >
            <path
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                fill="#4285F4"
            />
            <path
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                fill="#34A853"
            />
            <path
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                fill="#FBBC05"
            />
            <path
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                fill="#EA4335"
            />
        </svg>
    );
}

/** Google OAuth button — posts provider=google to the current route's action
    (which redirects to Google). Disabled while ANY submit on the page is in
    flight; shows a spinner while it is specifically the Google redirect. */
export function GoogleAuthButton({ label }: { label: string }) {
    const navigation = useNavigation();
    const submitting = navigation.state !== 'idle';
    const pending =
        submitting && navigation.formData?.get('provider') === 'google';
    return (
        <Form method="post">
            <input type="hidden" name="provider" value="google" />
            <Button
                type="submit"
                disabled={submitting}
                className={AUTH_GOOGLE_BUTTON_CLASS}
            >
                {/* Fixed-width slot so the icon → spinner swap never shifts the label. */}
                <span className="flex w-5 items-center justify-center">
                    {pending ? (
                        <ButtonSpinner className="!h-5 !w-5" />
                    ) : (
                        <GoogleIcon />
                    )}
                </span>
                {label}
            </Button>
        </Form>
    );
}
