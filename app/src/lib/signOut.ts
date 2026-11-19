// Signing out of the app, as its own button does: a POST to /logout, which ends the session and leads to the sign-in
// page. Work keeps a copy of what it showed in this browser (screens/work/kept.ts); a browser others may use forgets
// the account's copy first.
import { dropKept } from '@/screens/work/keptKey';

export async function signOut(account?: string | null): Promise<void> {
    if (account) await dropKept(account);
    const form = document.createElement('form');
    form.method = 'post';
    form.action = '/logout';
    document.body.appendChild(form);
    form.submit();
}
