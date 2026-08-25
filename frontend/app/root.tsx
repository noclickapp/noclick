import { Links, Meta, Outlet, Scripts, ScrollRestoration, useRouteError, isRouteErrorResponse, useLocation, type ShouldRevalidateFunctionArgs } from 'react-router';
import type { LinksFunction, LoaderFunctionArgs, MetaFunction } from 'react-router';
import { json } from '~/lib/routerResponse';
import { Toaster } from '~/components/ui/sonner';
import { NavigationProgress } from '~/components/shared/NavigationProgress';
import { createServerSupabaseClient } from '~/lib/supabase';
import { isCacheableMarketingPath } from '~/lib/marketingCache';
import { useEffect } from 'react';
import { ErrorPage } from '~/components/error/ErrorPage';
import { applyTheme, watchSystemTheme } from '~/lib/theme';
import {
    isTransientChunkError,
    tryGuardedReload,
} from '~/lib/staleChunkReload';
import { buildSeoMeta, DEFAULT_TITLE, DEFAULT_DESCRIPTION } from '~/lib/seo';

import styles from './tailwind.css?url';
import '~/styles/button-3d.css';
import '@fontsource-variable/outfit';
import '@fontsource-variable/inter';

export const links: LinksFunction = () => [
    { rel: 'stylesheet', href: styles },
    // Preload the two woff2 font files Tailwind references via @fontsource so browsers
    // start fetching them before the CSS that names them is parsed. font-display: swap
    // means text still paints in fallback if these don't arrive in time.
    // Build-output paths, so they exist only after a production build — emitting
    // them in dev is two guaranteed 404s per page load on a self-hosted install.
    ...(import.meta.env.PROD
        ? ([
              {
                  rel: 'preload',
                  href: '/assets/inter-latin-wght-normal-Dx4kXJAl.woff2',
                  as: 'font',
                  type: 'font/woff2',
                  crossOrigin: 'anonymous',
              },
              {
                  rel: 'preload',
                  href: '/assets/outfit-latin-wght-normal-Bc-8i84L.woff2',
                  as: 'font',
                  type: 'font/woff2',
                  crossOrigin: 'anonymous',
              },
          ] as const)
        : []),
    // Favicon set, kept deliberately minimal: every extra icon link is another
    // candidate a third-party picker can resolve badly. ICO first with an explicit
    // sizes="32x32" — Chrome ignores sizes="any" and would prefer the ICO outright;
    // the SVG must follow it to win in browsers that support one. 192/512 rasters
    // are declared once, in the manifest, rather than duplicated as links here.
    { rel: 'icon', type: 'image/x-icon', href: '/favicon.ico', sizes: '32x32' },
    { rel: 'icon', type: 'image/svg+xml', href: '/icon.svg' },
    {
        rel: 'apple-touch-icon',
        sizes: '180x180',
        href: '/apple-touch-icon.png',
    },
    { rel: 'manifest', href: '/site.webmanifest' },
];

// Site-wide fallback meta — any route that does not export `meta` inherits this.
// Routes that export their own `meta` should fully override these tags.
export const meta: MetaFunction = () =>
    buildSeoMeta({
        title: DEFAULT_TITLE,
        description: DEFAULT_DESCRIPTION,
    });

export async function loader({ request }: LoaderFunctionArgs) {
    // Cacheable marketing paths get a static, visitor-free document (no getUser,
    // no Set-Cookie) so a shared edge cache can serve it to everyone — one
    // personalized byte here would poison the shared cache. Auth-aware nav and
    // telemetry identity resolve client-side via usePublicSession instead.
    if (isCacheableMarketingPath(new URL(request.url).pathname)) {
        return json({ userID: null, isAuthenticated: false });
    }

    // Create headers for potential cookie updates from token refresh
    const headers = new Headers();
    const supabase = createServerSupabaseClient(request, headers);
    const {
        data: { user },
    } = await supabase.auth.getUser();

    return json(
        {
            userID: user?.id || null, // Only pass userID if authenticated
            isAuthenticated: !!user,
        },
        { headers }
    );
}

// Root's loader only carries auth status, which flips solely on login/logout.
// Those already do full-document loads (AuthModal → window.location.reload, OAuth
// → window.location.href, NavBar logout → window.location.href), and form
// submissions revalidate by default. Crossing the /auth boundary (e.g.
// /auth/login → /dashboard via client nav) also revalidates so telemetry picks up
// the new identity. Every other client navigation skips root's getUser() network
// round-trip — which, without this, single-fetch re-ran on every transition.
export function shouldRevalidate({
    formAction,
    currentUrl,
    nextUrl,
    defaultShouldRevalidate,
}: ShouldRevalidateFunctionArgs) {
    if (formAction) return defaultShouldRevalidate;
    const crossedAuthBoundary =
        currentUrl.pathname.startsWith('/auth') !==
        nextUrl.pathname.startsWith('/auth');
    if (crossedAuthBoundary) return defaultShouldRevalidate;
    return false;
}

function AppContent() {
    const location = useLocation();
    // Re-resolve the theme on client navigation: leaving /dashboard forces dark
    // back on; returning restores the stored preference. First paint is handled
    // by the inline head script, toggles by setTheme.
    useEffect(() => {
        applyTheme(location.pathname);
    }, [location.pathname]);

    // OS scheme flips re-apply the theme while the stored choice is 'system'.
    useEffect(() => watchSystemTheme(), []);

    return (
        <>
            <NavigationProgress />
            <Outlet />
            <Toaster />
            <ScrollRestoration />
            <Scripts />
        </>
    );
}

// Runs before first paint so a stored light preference doesn't flash dark.
// Must mirror the route gate + storage key in app/lib/theme.ts; the regex is
// inlined because this executes before any bundle loads.
const THEME_INIT_SCRIPT = `try{var t=localStorage.getItem('nc-theme');if((t==='light'||(t==='system'&&!matchMedia('(prefers-color-scheme: dark)').matches))&&/^\\/(dashboard|b|credential\\/provide)(\\/|$)/.test(location.pathname)){document.documentElement.classList.remove('dark')}}catch(e){}`;

export default function App() {
    return (
        // suppressHydrationWarning: the inline theme script may strip the `dark`
        // class before React hydrates the server-rendered class attribute.
        <html lang="en" className="dark" suppressHydrationWarning>
            <head>
                <meta charSet="utf-8" />
                <meta
                    name="viewport"
                    content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover"
                />
                <script
                    dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }}
                />
                <Meta />
                <Links />
            </head>
            <body>
                <AppContent />
            </body>
        </html>
    );
}

// Global error boundary for catching all unhandled errors
export function ErrorBoundary() {
    const error = useRouteError();
    const isRouteError = isRouteErrorResponse(error);

    // Unhandled JS errors — auto-reload for transient chunk/network errors
    // (stale-deploy hashes, flaky mobile fetches), show error page for genuine
    // bugs. Matching + the once-per-30s reload guard live in staleChunkReload.
    const errorStr = error instanceof Error ? error.message : String(error);
    const isTransientNetworkError =
        !isRouteError && isTransientChunkError(errorStr);
    // Remix Fog-of-War (v3_lazyRouteDiscovery) throws this when a tab open
    // across a deploy asks for a route from a newer manifest. It's framework
    // control-flow, not a bug: Remix has ALREADY set window.location.href to
    // hard-reload onto the new bundle, so we neither report it nor reload
    // ourselves — just render nothing until the in-flight navigation lands.
    const isStaleDeployReload =
        !isRouteError && errorStr.includes('manifest version mismatch');

    useEffect(() => {
        // Route-level HTTP errors (404 etc.) have dedicated UI and aren't
        // render crashes — don't report them. A stale-deploy manifest reload
        // is expected framework churn, not a crash — also skip reporting so it
        // doesn't inflate the error rate and mask real regressions. For
        // everything else this is the only sink: window.onerror doesn't catch
        // React render errors.
        if (isRouteError || isStaleDeployReload) return;
        if (isTransientNetworkError && tryGuardedReload()) {
            console.error(
                '[ErrorBoundary] Transient network error, auto-reloading:',
                errorStr
            );
        }
    }, [
        isRouteError,
        isStaleDeployReload,
        isTransientNetworkError,
        errorStr,
        error,
    ]);

    // The boundary re-renders <html className="dark"> (the SSR default); on a
    // client-side error that would override a stored light preference, so
    // re-apply it. SSR'd error pages get the same via THEME_INIT_SCRIPT.
    useEffect(() => {
        applyTheme();
    }, []);

    // Route-level HTTP errors (404, 401, etc.) — show appropriate UI
    if (isRouteErrorResponse(error)) {
        let title = 'Error';
        let message = 'Something went wrong';

        switch (error.status) {
            case 404:
                title = 'Page Not Found';
                message =
                    "The page you're looking for doesn't exist or has been moved.";
                break;
            case 401:
                title = 'Unauthorized';
                message = 'You need to be logged in to access this page.';
                break;
            case 403:
                title = 'Forbidden';
                message = "You don't have permission to access this resource.";
                break;
            case 500:
                title = 'Server Error';
                message =
                    'An internal server error occurred. Our team has been notified.';
                break;
            default:
                title = `Error ${error.status}`;
                message = error.statusText || 'An unexpected error occurred.';
        }

        return (
            <html lang="en" className="dark" suppressHydrationWarning>
                <head>
                    <meta charSet="utf-8" />
                    <meta
                        name="viewport"
                        content="width=device-width, initial-scale=1, viewport-fit=cover"
                    />
                    <title>{`${title} - NoClick`}</title>
                    <script
                        dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }}
                    />
                    <Meta />
                    <Links />
                </head>
                <body>
                    <ErrorPage
                        title={title}
                        message={message}
                        code={error.status}
                        showStack={false}
                        showBackButton={error.status === 404}
                        showHomeButton={true}
                        showReloadButton={error.status >= 500}
                    />
                    <Scripts />
                </body>
            </html>
        );
    }

    if (isTransientNetworkError || isStaleDeployReload) {
        return null;
    }

    const errorMessage =
        error instanceof Error ? error : new Error('Unknown error');
    const isDevelopment = process.env.NODE_ENV === 'development';

    return (
        <html lang="en" className="dark" suppressHydrationWarning>
            <head>
                <meta charSet="utf-8" />
                <meta
                    name="viewport"
                    content="width=device-width, initial-scale=1, viewport-fit=cover"
                />
                <title>Error - NoClick</title>
                <script
                    dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }}
                />
                <Meta />
                <Links />
            </head>
            <body>
                <ErrorPage
                    title="Application Error"
                    message="An unexpected error occurred. Please try reloading the page."
                    error={errorMessage}
                    showStack={isDevelopment}
                    showBackButton={false}
                    showHomeButton={true}
                    showReloadButton={true}
                />
                <Scripts />
            </body>
        </html>
    );
}
