/** React Router framework-mode browser entry point. */

// MUST be first: installs the React DevTools hook before react-dom injects, so a
// runaway #185 commit loop is localized (see app/lib/debug/maxUpdateDepthProbe.ts).
import '~/lib/debug/maxUpdateDepthProbe';
import { HydratedRouter } from 'react-router/dom';
import { startTransition, StrictMode } from 'react';
import { hydrateRoot } from 'react-dom/client';

// Prevent crashes from third-party DOM mutations (PostHog, browser extensions,
// Google Translate, etc.) during React's commit phase. React assumes exclusive
// DOM ownership; external scripts that inject/move/remove nodes break that
// invariant and cause "removeChild" NotFoundErrors on route transitions.
// See: https://github.com/facebook/react/issues/11538#issuecomment-417803648
if (typeof Node !== 'undefined' && Node.prototype) {
    const origRemoveChild = Node.prototype.removeChild;
    Node.prototype.removeChild = function <T extends Node>(child: T): T {
        if (child.parentNode !== this) {
            console.warn('removeChild: child not found in parent, skipping', child);
            return child;
        }
        return origRemoveChild.call(this, child) as T;
    };

    const origInsertBefore = Node.prototype.insertBefore;
    Node.prototype.insertBefore = function <T extends Node>(newNode: T, refNode: Node | null): T {
        if (refNode && refNode.parentNode !== this) {
            console.warn('insertBefore: reference node not found in parent, skipping', refNode);
            return newNode;
        }
        return origInsertBefore.call(this, newNode, refNode) as T;
    };
}

// Register workflow test harness (needed in all envs for SDK bridge node access)
import('~/lib/workflowTestHarness').then(m => m.register());

// Override console methods to log to file in development
if (process.env.NODE_ENV === 'development') {
    // Register nc bridge for HMR-based test execution
    import('~/lib/nc/bridge');

    // Import channel for pushing errors to Claude Code
    const channelPromise = import('~/lib/nc/channel');

    const serializeArgs = (args: any[]): string =>
        args.map(a => {
            try { return typeof a === 'object' ? JSON.stringify(a) : String(a); }
            catch { return String(a); }
        }).join(' ');

    // Circuit-breaker: if /api/console isn't served (e.g. the route module is a
    // .ts resource route that routes.ts's .tsx-only filter drops), a 404 renders
    // the SSR error document on every forwarded log, flooding the dev server and
    // starving real routes. Disable forwarding permanently after the first
    // non-OK response so a dead endpoint can never loop.
    let logForwardingDisabled = false;
    const logToFile = (type: string, args: any[]) => {
        if (logForwardingDisabled) return;
        fetch('/api/console', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type, args: args.map(arg => {
                try {
                    return typeof arg === 'object' ? JSON.stringify(arg) : String(arg);
                } catch {
                    return String(arg);
                }
            })}),
        }).then(res => { if (!res.ok) logForwardingDisabled = true; })
          .catch(() => { logForwardingDisabled = true; });
    };

    /** Forward a message to the Claude Code channel with a contextual prefix */
    const pushChannel = (prefix: string, message: string, meta?: Record<string, string>) => {
        channelPromise.then(({ channel }) => channel.error(`${prefix} ${message}`, meta)).catch(() => {});
    };

    const originalLog = console.log;
    const originalError = console.error;
    const originalWarn = console.warn;
    const originalInfo = console.info;
    const originalDebug = console.debug;

    console.log = (...args) => {
        originalLog(...args);
        logToFile('log', args);
    };

    console.error = (...args) => {
        originalError(...args);
        logToFile('error', args);
        pushChannel('Frontend console.error:', serializeArgs(args), { source: 'console.error' });
    };

    console.warn = (...args) => {
        originalWarn(...args);
        logToFile('warn', args);
    };

    console.info = (...args) => {
        originalInfo(...args);
        logToFile('info', args);
    };

    console.debug = (...args) => {
        originalDebug(...args);
        logToFile('debug', args);
    };

    // Capture uncaught errors and unhandled promise rejections
    window.addEventListener('error', (event) => {
        const msg = `${event.message} at ${event.filename}:${event.lineno}:${event.colno}`;
        logToFile('error', [`[Uncaught] ${msg}`]);
        pushChannel('Uncaught frontend error:', msg, {
            source: 'uncaught',
            file: event.filename ?? '',
            line: String(event.lineno ?? ''),
        });
    });
    window.addEventListener('unhandledrejection', (event) => {
        const reason = event.reason;
        const msg = reason instanceof Error ? `${reason.message}\n${reason.stack}` : String(reason);
        logToFile('error', [`[UnhandledRejection] ${msg}`]);
        pushChannel('Unhandled promise rejection:', msg, { source: 'unhandledrejection' });
    });
}

startTransition(() => {
    hydrateRoot(
        document,
        <StrictMode>
            <HydratedRouter />
        </StrictMode>
    );
});
