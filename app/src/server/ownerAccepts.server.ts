// Whether NoClick gave this app its key (a copy deployed on NoClick): that key never accepts terms for a person, so the
// account's owner accepts them approving the call (src/sdk/held.ts), and a page leaves them out. A fact, not a secret.
// This module reads the app's settings to hand out that one field and nothing else, so no route needs the rest of them.
import type { RouterContextProvider } from 'react-router';
import { appConfigContext } from './config.server';

export function ownerAccepts(context: Readonly<RouterContextProvider>): boolean {
    return context.get(appConfigContext).keyGiven;
}
