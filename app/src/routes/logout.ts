// Signing out: a POST (a link or an image elsewhere can't sign the owner out) that removes this browser's session cookie.
import { plainText } from '@/server/responses.server';
import { signOut } from '@/server/session.server';
import type { Route } from './+types/logout';

export const action = (args: Route.ActionArgs) => signOut(args);

export function loader() {
    const refused = plainText(405, 'Sign out with a POST (the Sign out button).');
    refused.headers.set('allow', 'POST');
    return refused;
}
