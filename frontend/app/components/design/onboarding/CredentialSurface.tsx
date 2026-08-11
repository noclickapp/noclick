/* Scoped restyle wrapper for the real NodeCredentials UI on the black onboarding
   ground. The rules live in credential-surface.css — see that file for why this
   is a uniform treatment rather than a per-class remap. Nothing in
   NodeCredentials changes; its raised greys stay correct inside the config
   panel they were designed for. */

import { forwardRef, type ReactNode } from 'react';
import { cn } from '~/lib/utils';
import '~/styles/credential-surface.css';

export const CredentialSurface = forwardRef<
    HTMLDivElement,
    { children: ReactNode; className?: string }
>(function CredentialSurface({ children, className }, ref) {
    return (
        <div ref={ref} className={cn('nc-cred-surface', className)}>
            {children}
        </div>
    );
});
