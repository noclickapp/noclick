/*
Lander for password-reset links minted before the token_hash email templates
(the token-hash recovery change) — recovery now goes through /auth/confirm. Old links only reach this
route as GoTrue error redirects (their 1h tokens are long expired; e.g. a stale
email clicked weeks later, or a mail scanner consumed the link): show the error
page. Anything else lands from a dead bookmark: send it to request a fresh link.
*/
import { redirect, type LoaderFunctionArgs } from 'react-router';
import {
    parseAuthCallbackError,
    authCallbackErrorReason,
    authErrorPagePath,
} from '~/lib/authCallbackErrors';

export async function loader({ request }: LoaderFunctionArgs) {
    const requestUrl = new URL(request.url);

    const authError = parseAuthCallbackError(requestUrl.searchParams);
    if (authError) {
        console.error('[ResetPassword] Auth provider returned error:', authError);
        return redirect(authErrorPagePath(authCallbackErrorReason(authError)));
    }

    return redirect('/auth/forgot-password');
}
