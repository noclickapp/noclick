// The dashboard's Debug tab draws the page a deployment registers (lazy, so nothing loads until the tab opens),
// and the address params that page owns are cleared when leaving it. The engine registers none.
import type { ComponentType } from 'react';

let page: ComponentType | null = null;
let ownParams: readonly string[] = [];

export function registerDebugPage(
    component: ComponentType,
    params: readonly string[]
): void {
    page = component;
    ownParams = params;
}

export function getDebugPage(): ComponentType | null {
    return page;
}

/** The registered page's own address params. */
export function debugPageParams(): readonly string[] {
    return ownParams;
}
