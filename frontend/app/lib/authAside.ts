// What the sign-in pages show beside their form. The engine registers none, so the open edition's auth pages are the
// form alone; a deployment adds its own (hosted: the Text NoClick card, which has a number only it can show).
// `inline` asks for the small form that sits under the form on a narrow screen.
import type { ComponentType } from 'react';

export type AuthAside = ComponentType<{ inline?: boolean }>;

let aside: AuthAside | null = null;

export function registerAuthAside(Aside: AuthAside): void {
    aside = Aside;
}

export function getAuthAside(): AuthAside | null {
    return aside;
}
