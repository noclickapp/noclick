// Root route for the self-hosted edition: straight into the app.
// A brand-new install has no account yet, so it lands on the signup form
// ("set up your instance") rather than a login wall, which reads as being
// asked to log in to something you just installed. Once an account exists,
// `/` goes to the dashboard, whose loader handles unauthenticated visitors.

import { redirect } from 'react-router';

export const loader = async () => {
    const apiUrl = process.env.VITE_API_URL;
    if (apiUrl) {
        try {
            const response = await fetch(`${apiUrl}/api/public/instance-status`, {
                signal: AbortSignal.timeout(2000),
            });
            if (response.ok) {
                const { needs_setup: needsSetup } = await response.json();
                if (needsSetup) return redirect('/auth/register');
            }
        } catch {
            // Backend not up yet, or an older build without the endpoint —
            // the dashboard's own auth handling is a fine fallback.
        }
    }
    return redirect('/dashboard');
};

export default function Index() {
    return null;
}
