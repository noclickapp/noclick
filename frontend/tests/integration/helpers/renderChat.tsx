// renderChat — mounts the minimum React tree we need to integration-test
// chat behavior: WorkflowProvider (for the activeWorkflowEditorId hook) +
// the chat surface itself. Returns a controllable handle exposing:
//
//  - container:   the mounted DOM root (for snapshots / queries)
//  - socket:      the MockSocket — drive BE events via socket.serverEmit
//  - navigate(workflowId | null): swap the active workflow editor id
//                                  (mimics the user navigating between
//                                  workflows or away to a non-editor route)
//  - log:         test-time observability (logs key events; dumps state
//                  on unhandled errors and when assertions fail)
//  - cleanup():   unmount + restore the global socket
//
// Why a wrapper and not a real Remix route: Remix's router brings DOM
// + history + data-loader complexity that doesn't add coverage to the
// kind of state-coordination bugs we're targeting. The WorkflowProvider
// sets the same valtio store that useActiveWorkflowEditorId reads, so
// the hook's behavior matches production.

import { ReactNode, useState, useEffect } from 'react';
import { render, RenderResult, act } from '@testing-library/react';
import { WorkflowProvider } from '~/components/workflow/WorkflowContext';
import { activeGenStore } from '~/lib/activeGenStore';
import { graphRecords } from '~/lib/liveGraphStore';
import { installMockSocket, MockSocket } from './mockSocket';

interface RenderChatOptions {
    initialWorkflowId?: string | null;
    initialWorkflowName?: string;
    /** React subtree to render under the WorkflowProvider. Defaults to
     *  `<NoClick>` — pass a different children for tests that care
     *  about a specific chat surface (e.g., FlowCanvasEmptyState). */
    children?: ReactNode;
}

export interface ChatHarness {
    container: HTMLElement;
    socket: MockSocket;
    navigate: (workflowId: string | null) => void;
    log: TestLogger;
    cleanup: () => void;
    rerender: RenderResult['rerender'];
    // Snapshot helpers for assertions
    getMessagesText: () => string;
    getActiveGenSnapshot: () => unknown;
}

export class TestLogger {
    events: Array<{ t: number; tag: string; data?: unknown }> = [];
    private start = Date.now();

    log(tag: string, data?: unknown): void {
        this.events.push({ t: Date.now() - this.start, tag, data });
    }

    /** Dump full timeline to console; called by `cleanup` on failure
     *  via the harness `cleanup` path. */
    dump(): string {
        return this.events
            .map(e => {
                const s = e.data === undefined ? '' : ` ${JSON.stringify(e.data).slice(0, 200)}`;
                return `[${e.t.toString().padStart(5)}ms] ${e.tag}${s}`;
            })
            .join('\n');
    }
}

interface NavigatableWrapperProps {
    initialWorkflowId: string | null;
    initialWorkflowName: string;
    children: ReactNode;
    onNavigate: (fn: (id: string | null) => void) => void;
}

function NavigatableWrapper({
    initialWorkflowId,
    initialWorkflowName,
    children,
    onNavigate,
}: NavigatableWrapperProps) {
    const [wfId, setWfId] = useState<string | null>(initialWorkflowId);
    useEffect(() => {
        onNavigate(setWfId);
    }, [onNavigate]);
    if (!wfId) return <>{children}</>;
    return (
        <WorkflowProvider workflowId={wfId} workflowName={initialWorkflowName}>
            {children}
        </WorkflowProvider>
    );
}

export async function renderChat(opts: RenderChatOptions = {}): Promise<ChatHarness> {
    // Reset shared state so each test starts clean.
    Object.keys(activeGenStore.gens).forEach(k => delete activeGenStore.gens[k]);
    Object.keys(activeGenStore.byWorkflow).forEach(k => delete activeGenStore.byWorkflow[k]);
    Object.keys(activeGenStore.lastCommitted).forEach(k => delete activeGenStore.lastCommitted[k]);
    Object.keys(graphRecords).forEach(k => delete graphRecords[k]);

    const { socket, teardown } = installMockSocket();
    const log = new TestLogger();

    const children = opts.children ?? <DefaultChatRoot />;

    let setWorkflowId: ((id: string | null) => void) | null = null;
    const captureNav = (fn: (id: string | null) => void) => { setWorkflowId = fn; };

    const result = render(
        <NavigatableWrapper
            initialWorkflowId={opts.initialWorkflowId ?? null}
            initialWorkflowName={opts.initialWorkflowName ?? 'Test Workflow'}
            onNavigate={captureNav}
        >
            {children}
        </NavigatableWrapper>,
    );

    log.log('render-mounted', { workflowId: opts.initialWorkflowId });

    return {
        container: result.container,
        socket,
        navigate: (workflowId: string | null) => {
            log.log('navigate', { to: workflowId });
            act(() => {
                setWorkflowId?.(workflowId);
            });
        },
        log,
        cleanup: () => {
            log.log('cleanup');
            result.unmount();
            teardown();
        },
        rerender: result.rerender,
        getMessagesText: () => result.container.textContent ?? '',
        getActiveGenSnapshot: () => ({
            gens: Object.keys(activeGenStore.gens),
            byWorkflow: JSON.parse(JSON.stringify(activeGenStore.byWorkflow)),
        }),
    };
}

// Lazy-loaded chat root so importing the harness doesn't pull in
// the entire NoClick component graph at parse time. Uses React.lazy
// + Suspense so render() returns synchronously.
import { lazy, Suspense } from 'react';
const NoClickLazy = lazy(() =>
    import('~/components/chat/NoClick').then((mod) => ({ default: mod.NoClick }))
);
const ignoreExpandChange = () => {};
function DefaultChatRoot() {
    return (
        <Suspense fallback={<div data-testid="chat-loading">Loading chat…</div>}>
            <NoClickLazy
                isExpanded
                onExpandChange={ignoreExpandChange}
            />
        </Suspense>
    );
}
