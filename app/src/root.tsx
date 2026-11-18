// The document every page renders in, and the root route around them.
import type { ReactNode } from 'react';
import { isRouteErrorResponse, Links, Meta, Outlet, Scripts, ScrollRestoration } from 'react-router';
import '@fontsource-variable/inter/index.css';
import '@fontsource-variable/outfit/index.css';
import './app.css';

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
    return <Outlet />;
}

export function ErrorBoundary({ error }: { error: unknown }) {
    const notFound = isRouteErrorResponse(error) && error.status === 404;
    const detail = isRouteErrorResponse(error) ? error.statusText : error instanceof Error ? error.message : null;
    return (
        <main className="mx-auto max-w-xl px-6 py-16">
            <h1 className="text-2xl font-semibold">{notFound ? 'Page not found' : 'Something went wrong'}</h1>
            {!notFound && detail && <p className="mt-3 text-neutral-600 dark:text-neutral-400">{detail}</p>}
            {import.meta.env.DEV && error instanceof Error && error.stack && (
                <pre className="mt-6 overflow-x-auto text-xs">
                    <code>{error.stack}</code>
                </pre>
            )}
        </main>
    );
}
