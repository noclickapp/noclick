// Shared building blocks for the sign-in and sign-up pages so the two can't drift:
// the Google OAuth button (Remix Form + in-flight spinner), the small button
// spinner. Extracted when signup gained Google + the agent-scaffold treatment
// that login already had. The button self-detects its pending state via useNavigation.

import { Form, useNavigation } from 'react-router';
import GoogleMark from '~/components/icons/GoogleIcon';
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
    return <GoogleMark className="h-5 w-5 rr-block ph-no-capture" />;
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
