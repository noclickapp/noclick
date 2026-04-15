/**
 * By default, Remix will handle hydrating your app on the client for you.
 * You are free to delete this file if you'd like to, but if you ever want it revealed again, you can run `npx remix reveal` ✨
 * For more information, see https://remix.run/file-conventions/entry.client
 */

import { RemixBrowser } from '@remix-run/react';
import { startTransition, StrictMode } from 'react';
import { hydrateRoot } from 'react-dom/client';

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

    const logToFile = (type: string, args: any[]) => {
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
        }).catch(() => {});
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
            <RemixBrowser />
        </StrictMode>
    );
});
