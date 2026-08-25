// NoClick error page. Clean, centered, and fully theme-token driven so it reads
// as part of the product. Shows the brand (clickable home), the status code or a
// neutral error badge, a clear message, and obvious ways out (dashboard / back /
// reload). Used by the app's error boundaries.

import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { Button } from '~/components/ui/button';
import { LogoMark } from '~/components/shared/LogoMark';
import { AlertTriangle, Home, RefreshCw, ArrowLeft } from 'lucide-react';

interface ErrorPageProps {
    title?: string;
    message?: string;
    /** HTTP status code (404, 500, …) shown large when present. */
    code?: string | number;
    error?: Error;
    showStack?: boolean;
    showBackButton?: boolean;
    showHomeButton?: boolean;
    showReloadButton?: boolean;
}

export function ErrorPage({
    title = 'Something went wrong',
    message = "An unexpected error occurred. Try again, and if it keeps happening we'd love to hear about it.",
    code,
    error,
    showStack = false,
    showBackButton = true,
    showHomeButton = true,
    showReloadButton = true,
}: ErrorPageProps) {
    const navigate = useNavigate();

    // Client-only so new Date() doesn't cause an SSR/hydration mismatch.
    const [ts, setTs] = useState<string | null>(null);
    useEffect(() => setTs(new Date().toLocaleString()), []);

    return (
        <div className="flex min-h-screen flex-col items-center justify-center bg-background px-6 py-16 text-foreground">
            {/* Brand — clicking returns home */}
            <Link
                to="/"
                aria-label="NoClick home"
                className="mb-16 inline-flex items-center gap-2 opacity-90 transition-opacity hover:opacity-100"
            >
                <LogoMark className="h-[22px] w-[22px]" />
                <span className="text-lg font-bold tracking-tight">NoClick</span>
            </Link>

            <div className="w-full max-w-md text-center animate-in fade-in-0 slide-in-from-bottom-2 duration-500 fill-mode-both">
                {code != null ? (
                    <p className="font-brand text-[76px] font-bold leading-none tracking-tight text-foreground/90 tabular-nums">
                        {code}
                    </p>
                ) : (
                    <div className="mx-auto inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-muted">
                        <AlertTriangle className="h-6 w-6 text-muted-foreground" />
                    </div>
                )}

                <h1 className="mt-6 text-2xl font-semibold tracking-tight text-foreground">
                    {title}
                </h1>
                <p className="mx-auto mt-2.5 max-w-sm text-[15px] leading-relaxed text-muted-foreground">
                    {message}
                </p>

                {error && (
                    <div className="mt-6 rounded-xl border border-border bg-muted/40 p-3.5 text-left">
                        <p className="break-words font-mono text-[12.5px] leading-relaxed text-foreground/70">
                            {error.message}
                        </p>
                        {showStack && error.stack && (
                            <details className="group mt-2.5">
                                <summary className="cursor-pointer select-none font-mono text-[11px] text-muted-foreground transition-colors hover:text-foreground">
                                    <span className="group-open:hidden">
                                        Show stack trace
                                    </span>
                                    <span className="hidden group-open:inline">
                                        Hide stack trace
                                    </span>
                                </summary>
                                <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-muted-foreground">
                                    {error.stack}
                                </pre>
                            </details>
                        )}
                    </div>
                )}

                {/* Ways out — callers keep this to two buttons so the row stays balanced */}
                <div className="mt-8 flex flex-col justify-center gap-2.5 sm:flex-row">
                    {showHomeButton && (
                        <Button asChild className="w-full gap-2 sm:w-auto">
                            <Link to="/dashboard">
                                <Home />
                                Go to dashboard
                            </Link>
                        </Button>
                    )}
                    {showReloadButton && (
                        <Button
                            variant="outline"
                            onClick={() => window.location.reload()}
                            className="w-full gap-2 sm:w-auto"
                        >
                            <RefreshCw />
                            Reload
                        </Button>
                    )}
                    {showBackButton && (
                        <Button
                            variant="outline"
                            onClick={() => navigate(-1)}
                            className="w-full gap-2 sm:w-auto"
                        >
                            <ArrowLeft />
                            Go back
                        </Button>
                    )}
                </div>
            </div>

            {/* Footer meta */}
            <div className="mt-16 flex flex-col items-center gap-1.5 text-center text-sm animate-in fade-in-0 duration-700 delay-200 fill-mode-both">
                <p className="text-muted-foreground">
                    Need a hand?{' '}
                    <a
                        href="https://discord.gg/sHC2mrnss8"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-medium text-foreground/90 underline-offset-4 transition-colors hover:text-foreground hover:underline"
                    >
                        Contact support
                    </a>
                </p>
                {ts && (
                    <p className="font-mono text-xs text-muted-foreground/60">
                        {ts}
                    </p>
                )}
            </div>
        </div>
    );
}
