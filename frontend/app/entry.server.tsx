/** React Router framework-mode streaming server entry point. */

import { PassThrough } from 'node:stream';

import type { EntryContext, HandleDataRequestFunction } from 'react-router';
import { ServerRouter } from 'react-router';
import { isbot } from 'isbot';
import { renderToPipeableStream } from 'react-dom/server';
import { isCacheableMarketingPath } from '~/lib/marketingCache';

const ABORT_DELAY = 5_000;

// Root reads the visitor's session on every path but the cacheable marketing
// ones, so a route's shared-cache header stands only there: anywhere else the
// document or its .data could carry one person's data to the next visitor.
function keepPersonalResponsesPrivate(request: Request, headers: Headers) {
    const cacheControl = headers.get('Cache-Control');
    if (
        cacheControl &&
        !/\b(private|no-store)\b/i.test(cacheControl) &&
        !isCacheableMarketingPath(new URL(request.url).pathname)
    ) {
        headers.set('Cache-Control', 'private, no-store');
    }
}

export const handleDataRequest: HandleDataRequestFunction = (
    response,
    { request }
) => {
    keepPersonalResponsesPrivate(request, response.headers);
    return response;
};

export default async function handleRequest(
    request: Request,
    responseStatusCode: number,
    responseHeaders: Headers,
    reactRouterContext: EntryContext
) {
    keepPersonalResponsesPrivate(request, responseHeaders);
    return isbot(request.headers.get('user-agent') || '')
        ? handleBotRequest(
              request,
              responseStatusCode,
              responseHeaders,
              reactRouterContext
          )
        : handleBrowserRequest(
              request,
              responseStatusCode,
              responseHeaders,
              reactRouterContext
          );
}

function handleBotRequest(
    request: Request,
    responseStatusCode: number,
    responseHeaders: Headers,
    reactRouterContext: EntryContext
) {
    return new Promise((resolve, reject) => {
        let shellRendered = false;
        const { pipe, abort } = renderToPipeableStream(
            <ServerRouter
                context={reactRouterContext}
                url={request.url}
            />,
            {
                onAllReady() {
                    shellRendered = true;
                    const body = new PassThrough();
                    const stream = new ReadableStream({
                        start(controller) {
                            body.on('data', (chunk) => controller.enqueue(chunk));
                            body.on('end', () => controller.close());
                            body.on('error', (error) => controller.error(error));
                        },
                        cancel() {
                            body.destroy();
                        },
                    });

                    responseHeaders.set('Content-Type', 'text/html');

                    resolve(
                        new Response(stream, {
                            headers: responseHeaders,
                            status: responseStatusCode,
                        })
                    );

                    pipe(body);
                },
                onShellError(error: unknown) {
                    reject(error);
                },
                onError(error: unknown) {
                    responseStatusCode = 500;
                    // Log streaming rendering errors from inside the shell.  Don't log
                    // errors encountered during initial shell rendering since they'll
                    // reject and get logged in handleDocumentRequest.
                    if (shellRendered) {
                        console.error(error);
                    }
                },
            }
        );

        setTimeout(abort, ABORT_DELAY);
    });
}

function handleBrowserRequest(
    request: Request,
    responseStatusCode: number,
    responseHeaders: Headers,
    reactRouterContext: EntryContext
) {
    return new Promise((resolve, reject) => {
        let shellRendered = false;
        const { pipe, abort } = renderToPipeableStream(
            <ServerRouter
                context={reactRouterContext}
                url={request.url}
            />,
            {
                onShellReady() {
                    shellRendered = true;
                    const body = new PassThrough();
                    const stream = new ReadableStream({
                        start(controller) {
                            body.on('data', (chunk) => controller.enqueue(chunk));
                            body.on('end', () => controller.close());
                            body.on('error', (error) => controller.error(error));
                        },
                        cancel() {
                            body.destroy();
                        },
                    });

                    responseHeaders.set('Content-Type', 'text/html');

                    resolve(
                        new Response(stream, {
                            headers: responseHeaders,
                            status: responseStatusCode,
                        })
                    );

                    pipe(body);
                },
                onShellError(error: unknown) {
                    reject(error);
                },
                onError(error: unknown) {
                    responseStatusCode = 500;
                    // Log streaming rendering errors from inside the shell.  Don't log
                    // errors encountered during initial shell rendering since they'll
                    // reject and get logged in handleDocumentRequest.
                    if (shellRendered) {
                        console.error(error);
                    }
                },
            }
        );

        setTimeout(abort, ABORT_DELAY);
    });
}
