/**
 * By default, Remix will handle hydrating your app on the client for you.
 * You are free to delete this file if you'd like to, but if you ever want it revealed again, you can run `npx remix reveal` ✨
 * For more information, see https://remix.run/file-conventions/entry.client
 */

import { RemixBrowser } from '@remix-run/react';
import { startTransition, StrictMode } from 'react';
import { hydrateRoot } from 'react-dom/client';

// Override console methods to log to file in development
if (process.env.NODE_ENV === 'development') {
    // Register workflow test harness
    import('~/lib/workflowTestHarness').then(m => m.register());
    // Register nc bridge for HMR-based test execution
    import('~/lib/nc/bridge');

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
        }).catch(() => {
            // Silently fail if logging endpoint is unavailable
        });
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
}

startTransition(() => {
    hydrateRoot(
        document,
        <StrictMode>
            <RemixBrowser />
        </StrictMode>
    );
});
