// The server entry: React Router renders every document here and passes every data answer through
// `handleDataRequest`, including the few it answers before any middleware runs (a method no route takes, a path no
// route matches). Those get the gate here (src/server/gate.server.ts); everything else has had it already. Web
// streams only, so it renders the same under Node and any runtime with fetch's Request and Response.
import { isbot } from 'isbot';
import { renderToReadableStream } from 'react-dom/server';
import { ServerRouter, type EntryContext, type HandleDataRequestFunction, type RouterContextProvider } from 'react-router';
import { gateRanContext, gateUnseen, withSecurityHeaders } from '@/server/gate.server';

/** How long a page's deferred data may stream before React Router gives up on it. */
export const streamTimeout = 5_000;

export default async function handleRequest(
    request: Request,
    status: number,
    headers: Headers,
    routerContext: EntryContext,
    loadContext: RouterContextProvider,
): Promise<Response> {
    if (!loadContext.get(gateRanContext)) {
        const refused = await gateUnseen(request, 'document');
        if (refused) return withSecurityHeaders(request, refused);
    }
    let shellRendered = false;
    const body = await renderToReadableStream(<ServerRouter context={routerContext} url={request.url} />, {
        signal: AbortSignal.timeout(streamTimeout + 1_000),
        onError(error: unknown) {
            status = 500;
            // An error before the shell rendered is React Router's to report; one after it is only seen here.
            if (shellRendered) console.error(error);
        },
    });
    shellRendered = true;
    // A crawler, or a page with no client rendering, gets the whole document at once.
    const userAgent = request.headers.get('user-agent');
    if ((userAgent && isbot(userAgent)) || routerContext.isSpaMode) await body.allReady;
    headers.set('content-type', 'text/html');
    return withSecurityHeaders(request, new Response(body, { headers, status }));
}

export const handleDataRequest: HandleDataRequestFunction = async (response, { request, context }) => {
    if (!(context as RouterContextProvider).get(gateRanContext)) {
        const refused = await gateUnseen(request, 'data');
        if (refused) return withSecurityHeaders(request, refused);
    }
    return withSecurityHeaders(request, response);
};
