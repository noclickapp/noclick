import type { ReactNode } from 'react';

/** Community builds do not install a product-analytics provider. */
export function PHProvider({ children }: { children: ReactNode }) {
    return <>{children}</>;
}
