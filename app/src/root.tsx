// The document every page renders in, and the root route around them.
import { useEffect, useMemo, type ReactNode } from 'react';
import {
    isRouteErrorResponse,
    Links,
    Meta,
    Outlet,
    Scripts,
    ScrollRestoration,
    useLoaderData,
    useLocation,
    type LoaderFunctionArgs,
    type MiddlewareFunction,
} from 'react-router';
import '@fontsource-variable/inter/index.css';
import '@fontsource-variable/outfit/index.css';
import { isSetupData, SetupScreen } from '@/screens/setup/SetupScreen';
import { ClientProvider } from '@/sdk/client';
import { proxiedClient } from '@/sdk/proxied';
import { ownerAccepts } from '@/server/ownerAccepts.server';
import { gate, securityHeaders } from '@/server/gate.server';
import { Toaster } from '@/ui/sonner';
import { applyTheme, themeInitScript, watchSystemTheme } from '@/ui/theme';
import { PAGE_TITLE } from '@/ui/titles';
import './app.css';

// What a fork adds without editing the app's own files: every module under src/custom/ runs once, before any page
// renders, which is where it fills the app's slots (src/slots.ts; src/custom/README.md shows how).
import.meta.glob('./custom/*.{ts,tsx}', { eager: true });

/** Applies the stored theme before the first paint, so a page a person set to light never flashes dark. Inline: it
 *  runs before any bundle. */
const THEME_INIT_SCRIPT = themeInitScript();

/** The gate inside React Router: the app's settings, then the owner's session (src/server/gate.server.ts), with the
 *  security headers on every answer, the error pages' included. The server's entry has run the same gate first. */
export const middleware: MiddlewareFunction<Response>[] = [securityHeaders, gate];

/** The page's origin, for the SDK client while the page renders on the server, and whether NoClick gave the app its
 *  key (the gate's checked config): terms are then the account's owner's to accept. */
export function loader({ request, context }: LoaderFunctionArgs) {
    return { origin: new URL(request.url).origin, ownerAccepts: ownerAccepts(context) };
}

/** The origin the page is served from: the window's in the browser, the request's while rendering on the server. */
function pageOrigin(loaded: { origin: string } | undefined): string {
    if (typeof window !== 'undefined') return window.location.origin;
    if (!loaded) throw new Error('The root loader gives the page its origin while it renders on the server.');
    return loaded.origin;
}

export function Layout({ children }: { children: ReactNode }) {
    return (
        // Dark is the default theme (src/ui/tokens.css); the script below takes the class off for a person who chose
        // light (src/ui/theme.ts), which is why React is told not to mind the difference.
        <html lang="en" className="dark" suppressHydrationWarning>
            <head>
                <meta charSet="utf-8" />
                <meta name="viewport" content="width=device-width, initial-scale=1" />
                <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
                <Meta />
                <Links />
            </head>
            <body className="antialiased">
                {children}
                <ScrollRestoration />
                <Scripts />
            </body>
        </html>
    );
}

/** Keeps the page in the theme its person chose: on every page they move to, and when their system's own changes. */
function useTheme(): void {
    const { pathname } = useLocation();
    useEffect(() => applyTheme(pathname), [pathname]);
    useEffect(() => watchSystemTheme(), []);
}

export default function App() {
    useTheme();
    const loaded = useLoaderData<typeof loader>() as { origin: string; ownerAccepts: boolean } | undefined;
    const origin = pageOrigin(loaded);
    // Screens read NoClick through this client (useClient()): it calls this app's server, which holds the key.
    const client = useMemo(() => proxiedClient(origin), [origin]);
    return (
        <ClientProvider client={client} ownerAccepts={loaded?.ownerAccepts ?? false}>
            <Outlet />
            <Toaster />
        </ClientProvider>
    );
}

export function ErrorBoundary({ error }: { error: unknown }) {
    // A setting is missing or unusable: the gate's 503 carries which (names only).
    if (isRouteErrorResponse(error) && isSetupData(error.data)) return <SetupScreen problems={error.data.setup} />;
    const notFound = isRouteErrorResponse(error) && error.status === 404;
    const detail = isRouteErrorResponse(error) ? error.statusText : error instanceof Error ? error.message : null;
    return (
        <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-3 px-6 py-16">
            <h1 className={PAGE_TITLE}>{notFound ? 'Page not found' : 'Something went wrong'}</h1>
            {!notFound && detail && <p className="text-[14px] text-muted-foreground">{detail}</p>}
            {notFound && (
                <p className="text-[14px]">
                    <a className="text-muted-foreground underline underline-offset-4 hover:text-foreground" href="/">
                        Go to your account
                    </a>
                </p>
            )}
            {import.meta.env.DEV && error instanceof Error && error.stack && (
                <pre className="mt-6 overflow-x-auto text-xs">
                    <code>{error.stack}</code>
                </pre>
            )}
        </main>
    );
}
