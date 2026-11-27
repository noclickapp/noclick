// Signing out of the app, as its own button does: a POST to /logout, which ends the session and leads to the sign-in
// page. The browser keeps copies of what screens showed (@/lib/kept); a browser others may use forgets them first.
import { forgetKept } from '@/lib/kept';

export async function signOut(): Promise<void> {
    await forgetKept();
    const form = document.createElement('form');
    form.method = 'post';
    form.action = '/logout';
    document.body.appendChild(form);
    form.submit();
}
