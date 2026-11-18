// NoClick's API as this app is set to reach it (NOCLICK_API_URL, or NoClick's own). An address, not a secret: a page
// prints it in the commands it hands a person. This module reads the app's settings to hand out that one field and
// nothing else, so no route needs the rest of them.
import type { RouterContextProvider } from 'react-router';
import { appConfigContext } from './config.server';

export function apiUrl(context: Readonly<RouterContextProvider>): string {
    return context.get(appConfigContext).apiUrl;
}
