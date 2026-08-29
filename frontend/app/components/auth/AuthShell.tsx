/**
 * Shared production shell for the shared authentication layout.
 * It owns the brand and editorial hierarchy while callers keep their existing forms and auth behavior.
 */
import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { LogoMark } from '~/components/shared/LogoMark';
import { cn } from '~/lib/utils';

export function AuthShellBrand({ compact = false }: { compact?: boolean }) {
    return (
        <Link
            to="/"
            data-testid="auth-shell-brand"
            data-compact={compact || undefined}
            className="inline-flex self-start items-center gap-2.5 text-foreground transition-opacity hover:opacity-75"
        >
            <LogoMark
                width={compact ? 22 : 28}
                height={compact ? 22 : 28}
                style={{
                    width: compact ? '1.375rem' : '1.75rem',
                    height: compact ? '1.375rem' : '1.75rem',
                }}
                className="shrink-0 rr-block ph-no-capture"
            />
            <span
                className={cn(
                    'font-brand font-semibold tracking-tight',
                    compact ? 'text-lg' : 'text-2xl'
                )}
            >
                NoClick
            </span>
        </Link>
    );
}

export function AuthShellHeading({
    eyebrow,
    title,
    mutedTitle,
    description,
    compact = false,
}: {
    eyebrow?: string;
    title: string;
    mutedTitle?: string;
    description: string;
    compact?: boolean;
}) {
    return (
        <div>
            {eyebrow ? (
                <p className="mb-5 font-mono text-xs uppercase tracking-widest text-muted-foreground">
                    {eyebrow}
                </p>
            ) : null}
            <h1
                className={cn(
                    'font-brand font-medium leading-none tracking-tight text-foreground',
                    compact ? 'text-3xl' : 'text-4xl sm:text-5xl'
                )}
            >
                {title}
                {mutedTitle ? (
                    <span className="block text-muted-foreground">
                        {mutedTitle}
                    </span>
                ) : null}
            </h1>
            <p className="mt-5 max-w-sm text-sm leading-6 text-muted-foreground">
                {description}
            </p>
        </div>
    );
}

export function AuthShellPage({
    eyebrow,
    title,
    mutedTitle,
    description,
    children,
    footer,
}: {
    eyebrow?: string;
    title: string;
    mutedTitle?: string;
    description: string;
    children: ReactNode;
    footer: ReactNode;
}) {
    return (
        <div
            data-testid="auth-shell-page"
            className="flex min-h-screen w-full flex-col py-8 lg:py-10"
        >
            <AuthShellBrand />
            <div className="my-auto py-12">
                <AuthShellHeading
                    eyebrow={eyebrow}
                    title={title}
                    mutedTitle={mutedTitle}
                    description={description}
                />
                <div className="mt-9">{children}</div>
                {/* The way out sits with the form, not at the foot of the page. */}
                <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-muted-foreground">
                    {footer}
                </div>
            </div>
        </div>
    );
}

export const THESIS_INPUT_CLASS =
    'h-11 w-full rounded-xl border border-input bg-background px-4 text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-foreground focus:ring-0';

export const THESIS_PRIMARY_BUTTON_CLASS =
    'relative flex h-11 w-full items-center justify-center rounded-xl bg-primary text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50';

export const AUTH_GOOGLE_BUTTON_CLASS =
    'flex h-12 w-full items-center justify-center gap-2.5 rounded-xl border border-border bg-card text-sm font-medium text-foreground transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-70';

export function AuthShellDivider({
    label = 'or use email',
}: {
    label?: string;
}) {
    return (
        <div className="my-5 flex items-center gap-3 font-mono text-[0.625rem] uppercase tracking-[0.18em] text-muted-foreground">
            <span className="h-px flex-1 bg-border" />
            {label}
            <span className="h-px flex-1 bg-border" />
        </div>
    );
}
