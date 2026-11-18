// The document every page renders in, and the root route around them.
import { useMemo, type ReactNode } from 'react';
import {
    isRouteErrorResponse,
    Links,
    Meta,
    Outlet,
    Scripts,
    ScrollRestoration,
    useLoaderData,
    type LoaderFunctionArgs,
    type MiddlewareFunction,
} from 'react-router';
import '@fontsource-variable/inter/index.css';
import '@fontsource-variable/outfit/index.css';
import { isSetupData, SetupScreen } from '@/screens/setup/SetupScreen';
import { ClientProvider } from '@/sdk/client';
import { proxiedClient } from '@/sdk/proxied';
import { gate, securityHeaders } from '@/server/gate.server';
import { PAGE_TITLE } from '@/ui/titles';
import './app.css';

/** The gate inside React Router: the app's settings, then the owner's session (src/server/gate.server.ts), with the
 *  security headers on every answer, the error pages' included. The server's entry has run the same gate first. */
export const middleware: MiddlewareFunction<Response>[] = [securityHeaders, gate];

/** The page's origin, for the SDK client while the page renders on the server. */
export function loader({ request }: LoaderFunctionArgs) {
    return { origin: new URL(request.url).origin };
}

/** The origin the page is served from: the window's in the browser, the request's while rendering on the server. */
function pageOrigin(loaded: { origin: string } | undefined): string {
    if (typeof window !== 'undefined') return window.location.origin;
    if (!loaded) throw new Error('The root loader gives the page its origin while it renders on the server.');
    return loaded.origin;
}

export function Layout({ children }: { children: ReactNode }) {
    return (
        // Dark is the default theme (src/ui/tokens.css).
        <html lang="en" className="dark">
            <head>
                <meta charSet="utf-8" />
                <meta name="viewport" content="width=device-width, initial-scale=1" />
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

export default function App() {
    const origin = pageOrigin(useLoaderData<typeof loader>() as { origin: string } | undefined);
    // Screens read NoClick through this client (useClient()): it calls this app's server, which holds the key.
    const client = useMemo(() => proxiedClient(origin), [origin]);
    return (
        <ClientProvider client={client}>
            <Outlet />
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
