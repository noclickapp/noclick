// The sign-in pages' layout: the form on the left, and beside it on a wide screen whatever the deployment registers
// (`registerAuthAside`; hosted, the Text NoClick card) or a page's own `rightPanel`. With neither, the form stands
// alone. On a narrow screen the aside's small form follows the form.

import type { ReactNode } from 'react';
import { getAuthAside } from '~/lib/authAside';
import '@fontsource/instrument-serif/400.css';
import '@fontsource/instrument-serif/400-italic.css';

interface AuthLayoutProps {
    children: ReactNode;
    showRightPanel?: boolean;
    /** Replaces the registered aside in the right panel (e.g. the agent-scaffold preview when a visitor arrives from
        an /agents SEO CTA). */
    rightPanel?: ReactNode;
}

export function AuthLayout({ children, showRightPanel = true, rightPanel }: AuthLayoutProps) {
    const Aside = getAuthAside();
    const panel = rightPanel ?? (Aside ? <Aside /> : null);

    return (
        <div className="flex min-h-screen bg-background text-foreground">
            <div data-testid="auth-left-panel" className="flex flex-1 flex-col items-center justify-center px-6 sm:px-12 lg:px-16">
                <div className="relative z-10 w-full max-w-md">{children}</div>
                {showRightPanel && !rightPanel && Aside && (
                    <div className="w-full max-w-md pb-10 lg:hidden">
                        <Aside inline />
                    </div>
                )}
            </div>

            {showRightPanel && panel && (
                <div
                    data-testid="auth-right-panel"
                    className={`relative hidden overflow-hidden bg-foreground/[0.03] lg:block ${rightPanel ? 'lg:w-1/2 xl:w-[55%]' : 'lg:w-[45%]'}`}
                >
                    {panel}
                </div>
            )}
        </div>
    );
}
