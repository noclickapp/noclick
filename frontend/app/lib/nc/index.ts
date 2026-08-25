// NoClick test helper library — reusable utilities for browser-based testing and debugging.
// Import in test files: import { nc } from '~/lib/nc';
//
// Quick reference (call nc.help() for full details):
//   nc.node('id')              → full node data (operation, config, type, etc.)
//   nc.node('id').config       → node's config object
//   nc.nodes.list()            → all nodes [{id, type, data}]
//   nc.nodes.select('id')      → select node, opens config panel
//   nc.nodes.update('id', {})  → merge data into node
//   nc.nodes.delete('id')      → remove node + edges
//   nc.dom.qs('selector')      → querySelector
//   nc.dom.getText('selector') → element text content
//   nc.dom.click('selector')   → click element
//   nc.dom.type('selector', t) → set input value (triggers React onChange)
//   nc.wait.ms(100)            → sleep 100ms
//   nc.wait.until(() => cond)  → poll until condition is true
//   nc.wait.forElement('sel')  → wait for element to appear
//   nc.assert.equal(a, b, msg) → strict equality assertion
//   nc.emit('mcp:builder_event', data) → emit socket event directly
//   nc.configPanel()           → what's shown in the config panel right now
//   nc.help()                  → print all available APIs

import {
    getLocalComponentValtio,
    getCachedComponentValtio,
    state,
    cachedb,
} from '~/state';
import { socketReceiver } from '~/lib/socket-receiver';
import { deriveAgentChatConversationId } from '~/lib/agentChat';
import { agentChatSessionStore } from '~/lib/agentChatSessionStore';
import type { EventWithName } from '~/lib/socket-sender';

type Harness =
    (typeof import('~/lib/workflowTestHarness'))['workflowTestHarness'];

function getHarness(): Harness {
    return (window as any).__workflowTest;
}

// ── Core: quick node access ────────────────────────────────────────────

/** Get full node data by ID. Returns null if not found. */
function node(id: string): Record<string, any> | null {
    const n = getHarness()?.getNodeById(id);
    if (!n) return null;
    return {
        id: n.id,
        type: n.type,
        operation: n.data?.operation,
        label: n.data?.label,
        goal: n.data?.goal,
        config: n.data?.config || {},
        userFields: n.data?.userFields,
        ...n.data,
    };
}

// ── DOM helpers ─────────────────────────────────────────────────────────

const dom = {
    qs(selector: string, ctx: Element | Document = document): Element | null {
        return ctx.querySelector(selector);
    },
    qsa(selector: string, ctx: Element | Document = document): Element[] {
        return Array.from(ctx.querySelectorAll(selector));
    },
    getText(selector: string): string | null {
        return dom.qs(selector)?.textContent ?? null;
    },
    /** Get all text content matching a selector */
    getTexts(selector: string): string[] {
        return dom
            .qsa(selector)
            .map((el) => el.textContent?.trim() || '')
            .filter(Boolean);
    },
    click(selectorOrEl: string | Element): boolean {
        const el =
            typeof selectorOrEl === 'string'
                ? dom.qs(selectorOrEl)
                : selectorOrEl;
        if (!el) return false;
        (el as HTMLElement).click();
        return true;
    },
    clickWithModifiers(
        selectorOrEl: string | Element,
        modifiers: { metaKey?: boolean; ctrlKey?: boolean; shiftKey?: boolean }
    ): boolean {
        const el =
            typeof selectorOrEl === 'string'
                ? dom.qs(selectorOrEl)
                : selectorOrEl;
        if (!el) return false;
        const htmlEl = el as HTMLElement;
        const opts = { bubbles: true, cancelable: true, ...modifiers };
        htmlEl.dispatchEvent(new PointerEvent('pointerup', opts));
        htmlEl.dispatchEvent(new MouseEvent('click', opts));
        return true;
    },
    /** Set input value using native setter to trigger React's onChange */
    type(selectorOrEl: string | Element, text: string): boolean {
        const el = (
            typeof selectorOrEl === 'string'
                ? dom.qs(selectorOrEl)
                : selectorOrEl
        ) as HTMLInputElement | null;
        if (!el) return false;
        // Pick the setter for the element's OWN prototype — the input setter
        // called on a textarea throws (brand check), and the old ?? chain always
        // picked the input one.
        const proto =
            el instanceof HTMLTextAreaElement
                ? HTMLTextAreaElement.prototype
                : HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
        setter?.call(el, text);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
    },
    typeWithCursor(selectorOrEl: string | Element, text: string): boolean {
        const el = (
            typeof selectorOrEl === 'string'
                ? dom.qs(selectorOrEl)
                : selectorOrEl
        ) as HTMLInputElement | null;
        if (!el) return false;
        el.focus();
        const proto =
            el instanceof HTMLTextAreaElement
                ? HTMLTextAreaElement.prototype
                : HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
        setter?.call(el, text);
        el.setSelectionRange(text.length, text.length);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.dispatchEvent(new Event('select', { bubbles: true }));
        return true;
    },
    pressKey(selectorOrEl: string | Element, key: string): boolean {
        const el = (
            typeof selectorOrEl === 'string'
                ? dom.qs(selectorOrEl)
                : selectorOrEl
        ) as HTMLElement | null;
        if (!el) return false;
        el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
        el.dispatchEvent(new KeyboardEvent('keyup', { key, bubbles: true }));
        return true;
    },
    focus(selectorOrEl: string | Element): boolean {
        const el = (
            typeof selectorOrEl === 'string'
                ? dom.qs(selectorOrEl)
                : selectorOrEl
        ) as HTMLElement | null;
        if (!el) return false;
        el.focus();
        return true;
    },
};

// ── UI helpers ──────────────────────────────────────────────────────────

const ui = {
    /** Click a main tab by name: 'interface' | 'canvas' | 'logs' | 'setup' | 'resources' */
    clickTab(name: string): boolean {
        const normalized =
            name.charAt(0).toUpperCase() + name.slice(1).toLowerCase();
        // Title-attribute tabs first; fall back to exact-text buttons — the
        // canvas/interface view switcher renders plain text buttons with no title.
        const btn =
            dom.qs(`button[title="${normalized}"]`) ??
            dom.qs(`button[title="${name}"]`) ??
            [...document.querySelectorAll('button')].find(
                (b) =>
                    (b.textContent || '').trim() === normalized ||
                    (b.textContent || '').trim() === name
            ) ??
            null;
        if (!btn) return false;
        (btn as HTMLElement).click();
        return true;
    },
    getActiveTab(): string | null {
        const btns = dom.qsa('button[title]');
        for (const btn of btns) {
            if (btn.className.includes('bg-white')) {
                return btn.getAttribute('title')?.toLowerCase() ?? null;
            }
        }
        return null;
    },
};

// ── Workflow node helpers ────────────────────────────────────────────────

const nodes = {
    /** List all nodes with id, type, data */
    list: () => getHarness()?.getNodes() ?? [],
    /** List all edges [{id, source, target, sourceHandle, targetHandle, type}] */
    edges: () => getHarness()?.getEdges() ?? [],
    /** Number of nodes */
    count: () => getHarness()?.getNodes()?.length ?? 0,
    /** Get full node data by ID (same as nc.node(id)) */
    get: (id: string) => node(id),
    /** Get node output data */
    getOutput: (id: string) => getHarness()?.getReactState()?.[id]?.output,
    /** Delete node and connected edges (local-only — does NOT broadcast to the
     *  collab/YJS layer, so a synced node re-hydrates on the next sync). */
    delete: (id: string) => getHarness()?.deleteNode(id) ?? false,
    /** Delete a node via its on-canvas Delete button → ReactFlow deleteElements →
     *  onNodesChange, so the removal broadcasts to collaborators and the server
     *  forgets it. Use this to clean up broadcast-added nodes in tests. */
    deleteViaUI: (id: string): boolean => {
        const btn = document.querySelector(
            `[data-id="${id}"] button[title="Delete node"]`
        );
        if (!btn) return false;
        btn.dispatchEvent(
            new MouseEvent('click', { bubbles: true, cancelable: true })
        );
        return true;
    },
    /** Add a node with the given id, type, and config */
    add: (
        id: string,
        type: string,
        config?: Record<string, unknown>,
        position?: { x: number; y: number }
    ) => getHarness()?.addNode(id, type, config ?? {}, position) ?? false,
    /** Merge updates into node.data */
    update: (id: string, data: Record<string, unknown>) =>
        getHarness()?.updateNodeData(id, data) ?? false,
    /** Add edge between two nodes */
    addEdge: (source: string, target: string, sourceHandle?: string) =>
        getHarness()?.addEdge({ source, target, sourceHandle }) ?? false,
    /** Run node with dependencies */
    run: (id: string) => getHarness()?.runNodeWithDeps(id),
    /** Current workflow ID */
    workflowId: () => getHarness()?.getWorkflowId() ?? null,
    /** Select a node, opening its config panel in the sidebar */
    select: (id: string) => {
        const workflowId = getHarness()?.getWorkflowId();
        document.dispatchEvent(
            new CustomEvent('noclick:workflow:select-node', {
                detail: { nodeId: id, workflowId },
            })
        );
    },
    /** Click a node element on the canvas */
    click: (id: string): boolean => {
        const el = document.querySelector(`[data-id="${id}"]`);
        if (!el) return false;
        el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        return true;
    },
    /** Summary of all nodes: [{id, type, operation, label}] */
    summary: () =>
        (getHarness()?.getNodes() ?? []).map((n: any) => ({
            id: n.id,
            type: n.type,
            operation: n.data?.operation,
            label: n.data?.label,
        })),
};

// ── Config panel inspection ─────────────────────────────────────────────

/** Get info about the currently visible config panel. Returns null if no panel is open. */
function configPanel(): Record<string, any> | null {
    // The operation picker renders as a searchable select or button group
    const sidebar =
        document.querySelector('[class*="FlowHelperView"]') ||
        document.querySelector('[data-testid="config-panel"]');
    if (!sidebar) return null;

    // Find selected operation from the operation picker
    // It renders as a button with data-selected or as the active item in a select
    const opSelector = sidebar.querySelector(
        '[data-field-key="operation"] select'
    );
    const selectedOp = (opSelector as HTMLSelectElement)?.value ?? null;

    // Find the operation from a SearchableEnumField (rendered as a combobox button)
    const searchableOp = sidebar.querySelector(
        '[data-field-key="operation"] button[role="combobox"]'
    );
    const searchableOpText = searchableOp?.textContent?.trim() ?? null;

    // Get all visible field keys
    const fieldElements = sidebar.querySelectorAll('[data-field-key]');
    const visibleFields: string[] = [];
    fieldElements.forEach((el) => {
        const key = el.getAttribute('data-field-key');
        if (key) visibleFields.push(key);
    });

    // Get validation errors
    const errorEls = sidebar.querySelectorAll(
        '.text-amber-200, .text-red-400, [class*="error"]'
    );
    const errors: string[] = [];
    errorEls.forEach((el) => {
        const text = el.textContent?.trim();
        if (text) errors.push(text);
    });

    // Get the node type label
    const nodeLabel =
        sidebar
            .querySelector('h3, [class*="node-label"]')
            ?.textContent?.trim() ?? null;

    return {
        nodeLabel,
        selectedOperation: selectedOp || searchableOpText,
        visibleFields,
        errors: errors.length > 0 ? errors : null,
    };
}

// ── Socket / event helpers ──────────────────────────────────────────────

/** Simulate a server→client socket event by triggering all registered handlers.
 * Usage: nc.emit('mcp:builder_event', {workflow_id: '...', event_type: 'node_updated', data: {...}})
 */
function emit(eventName: string, ...args: any[]): void {
    // Use the socket receiver's internal dispatch to trigger handlers
    // just as if the server had sent the event
    (socketReceiver as any).handleEvent(eventName, args);
}

/** Send a socket event to the backend (request/response pattern) */
function send(event: EventWithName) {
    return getHarness()?.sendEvent(event);
}

// ── Agent chat test hygiene ─────────────────────────────────────────────
//
// Tests that drive AgentChatBlock's REAL send path (even with the socket
// stubbed) leave persistent side effects: a model switch mints a new
// conversation_key into the node config — persisted by autosave — and seeds a
// session with isStreaming=true that nothing will ever clear, since the
// dispatch was swallowed. Left behind, the user's chat opens on a ghost thread
// wedged on a spinner, and the Run-popup hand-off queue refuses to drain
// behind that flag (2026-07-27 incident). Every such test must capture() the
// thread identity up front and restore() it in `finally`, listing every
// conversation it dispatched into or seeded.

const agentChat = {
    /** Snapshot the thread identity a chat send can mutate. */
    capture(nodeId: string): {
        nodeId: string;
        model: string | undefined;
        conversationKey: string | undefined;
    } {
        const config = (node(nodeId)?.config ?? {}) as Record<string, unknown>;
        return {
            nodeId,
            model: config.model as string | undefined,
            conversationKey: config.conversation_key as string | undefined,
        };
    },
    /** conversationId for a node's thread (its current key unless given). */
    conversationId(nodeId: string, key?: string): string {
        const config = (node(nodeId)?.config ?? {}) as Record<string, unknown>;
        return deriveAgentChatConversationId(
            nodes.workflowId(),
            nodeId,
            key ?? (config.conversation_key as string | undefined)
        );
    },
    /** Put the node back on its pre-test thread and drop every session the
     *  test touched. Dropping (not patching) is the point: the next mount
     *  cold-fetches persisted truth, which discards seeded echoes and wedged
     *  streaming flags in one move. */
    restore(
        captured: {
            nodeId: string;
            model: string | undefined;
            conversationKey: string | undefined;
        },
        touchedConversationIds: string[] = []
    ): void {
        const config: Record<string, unknown> = {};
        if (captured.model !== undefined) config.model = captured.model;
        if (captured.conversationKey !== undefined)
            config.conversation_key = captured.conversationKey;
        if (Object.keys(config).length)
            nodes.update(captured.nodeId, { config });
        for (const cid of touchedConversationIds) {
            delete agentChatSessionStore.sessions[cid];
        }
    },
};

// ── Valtio state helpers ────────────────────────────────────────────────

const valtioState = {
    local: (path: string) => getLocalComponentValtio(path),
    cached: (path: string) => getCachedComponentValtio(path),
    raw: () => state,
    rawCached: () => cachedb,
};

// ── Assertions ──────────────────────────────────────────────────────────

class AssertionError extends Error {
    constructor(msg: string) {
        super(msg);
        this.name = 'AssertionError';
    }
}

const assert = {
    equal(actual: unknown, expected: unknown, msg = '') {
        if (actual !== expected)
            throw new AssertionError(
                `${msg ? msg + ': ' : ''}Expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`
            );
    },
    deepEqual(actual: unknown, expected: unknown, msg = '') {
        if (JSON.stringify(actual) !== JSON.stringify(expected))
            throw new AssertionError(
                `${msg ? msg + ': ' : ''}Deep equality failed.\nExpected: ${JSON.stringify(expected)}\nGot: ${JSON.stringify(actual)}`
            );
    },
    truthy(val: unknown, msg = '') {
        if (!val)
            throw new AssertionError(
                `${msg ? msg + ': ' : ''}Expected truthy, got ${JSON.stringify(val)}`
            );
    },
    ok(val: unknown, msg = '') {
        if (!val)
            throw new AssertionError(
                `${msg ? msg + ': ' : ''}Expected truthy, got ${JSON.stringify(val)}`
            );
    },
    falsy(val: unknown, msg = '') {
        if (val)
            throw new AssertionError(
                `${msg ? msg + ': ' : ''}Expected falsy, got ${JSON.stringify(val)}`
            );
    },
    includes(haystack: unknown[] | string, item: unknown, msg = '') {
        const includes =
            typeof haystack === 'string'
                ? typeof item === 'string' && haystack.includes(item)
                : haystack.includes(item);
        if (!includes)
            throw new AssertionError(
                `${msg ? msg + ': ' : ''}Expected value to include ${JSON.stringify(item)}`
            );
    },
    gt(a: number, b: number, msg = '') {
        if (!(a > b))
            throw new AssertionError(
                `${msg ? msg + ': ' : ''}Expected ${a} > ${b}`
            );
    },
};

// ── Wait/timing ─────────────────────────────────────────────────────────

const wait = {
    ms: (ms: number) => new Promise<void>((r) => setTimeout(r, ms)),
    async until(
        fn: () => boolean | Promise<boolean>,
        timeoutMs = 5000,
        pollMs = 50
    ): Promise<void> {
        const deadline = Date.now() + timeoutMs;
        while (Date.now() < deadline) {
            if (await fn()) return;
            await wait.ms(pollMs);
        }
        throw new Error(`wait.until timed out after ${timeoutMs}ms`);
    },
    async forElement(selector: string, timeoutMs = 5000): Promise<Element> {
        const deadline = Date.now() + timeoutMs;
        while (Date.now() < deadline) {
            const el = document.querySelector(selector);
            if (el) return el;
            await wait.ms(50);
        }
        throw new Error(`Element "${selector}" not found after ${timeoutMs}ms`);
    },
    async forElementGone(selector: string, timeoutMs = 5000): Promise<void> {
        await wait.until(() => !document.querySelector(selector), timeoutMs);
    },
    /** Wait for a node's data to match a predicate */
    async forNode(
        nodeId: string,
        predicate: (data: any) => boolean,
        timeoutMs = 5000
    ): Promise<void> {
        await wait.until(() => {
            const n = node(nodeId);
            return n ? predicate(n) : false;
        }, timeoutMs);
    },
};

// ── Run helpers ─────────────────────────────────────────────────────────

const run = {
    /** The canvas Run button, or null while a run is in flight (it reads "Stop"). */
    button(): HTMLButtonElement | null {
        return (
            ([...document.querySelectorAll('button')].find(
                (b) => b.textContent?.trim() === 'Run'
            ) as HTMLButtonElement | null) ?? null
        );
    },
    isRunning(): boolean {
        return [...document.querySelectorAll('button')].some(
            (b) => b.textContent?.trim() === 'Stop'
        );
    },
    /** Clear an optimistic run that will never complete.
     *
     *  A test that stubs the socket swallows workflow:execute, so no
     *  workflow:started ever comes back and the toolbar stays on "Stop" for the
     *  full 60s safety-net window — long enough that the NEXT test finds no Run
     *  button and reports "the popup did not open", which looks exactly like a
     *  feature bug. Simulating the pair the backend would have sent settles it. */
    settlePending(executionId = 'nc-settle'): void {
        if (!run.isRunning()) return;
        const workflow_id = nodes.workflowId();
        emit('workflow:started', { workflow_id, execution_id: executionId });
        emit('workflow:complete', {
            workflow_id,
            execution_id: executionId,
            success: true,
        });
    },
    /** Dismiss whatever run-related popup is open, so the next press is clean. */
    closePopups(): void {
        document
            .querySelectorAll<HTMLElement>(
                '[data-incomplete-run-dialog] button[aria-label="Close"], [data-run-results-dialog] button[aria-label="Close"]'
            )
            .forEach((b) => b.click());
    },
};

// ── Help ────────────────────────────────────────────────────────────────

function help(): string {
    return `
nc — NoClick test/debug helpers
================================

QUICK NODE INSPECTION:
  nc.node('id')              → full node data {id, type, operation, label, config, ...}
  nc.node('id').operation    → selected operation string
  nc.node('id').config       → config object
  nc.nodes.summary()         → [{id, type, operation, label}] for all nodes
  nc.nodes.list()            → all nodes with full data
  nc.nodes.count()           → number of nodes
  nc.nodes.workflowId()      → current workflow UUID

NODE MANIPULATION:
  nc.nodes.select('id')      → select node, opens config panel
  nc.nodes.click('id')       → click node on canvas
  nc.nodes.update('id', {operation: 'x'})  → merge into node.data
  nc.nodes.delete('id')      → remove node + edges
  nc.nodes.addEdge('a','b')  → add edge
  nc.nodes.run('id')         → execute node with deps

CONFIG PANEL:
  nc.configPanel()           → {selectedOperation, visibleFields, errors, nodeLabel}

DOM:
  nc.dom.qs('selector')      → querySelector
  nc.dom.qsa('selector')     → querySelectorAll as array
  nc.dom.getText('selector') → textContent
  nc.dom.getTexts('sel')     → all matching elements' text
  nc.dom.click('selector')   → click
  nc.dom.type('sel', 'text') → set input value (triggers React)
  nc.dom.pressKey('sel','Enter') → keydown+keyup
  nc.dom.focus('sel')        → focus element

UI NAVIGATION:
  nc.ui.clickTab('canvas')   → switch sidebar tab
  nc.ui.getActiveTab()       → current tab name

WAITING:
  await nc.wait.ms(100)              → sleep
  await nc.wait.until(() => cond)    → poll until true (5s timeout)
  await nc.wait.forElement('sel')    → wait for element
  await nc.wait.forNode('id', n => n.operation === 'x')  → wait for node state

EVENTS:
  nc.emit('mcp:builder_event', {workflow_id, event_type, data})  → simulate server event
  nc.send({event_name: '...', ...})  → send to backend

STATE:
  nc.state.local('/path')    → Valtio local state
  nc.state.cached('/path')   → Valtio cached state
  nc.state.raw()             → root state proxy
  nc.state.rawCached()       → root cache proxy

ASSERTIONS:
  nc.assert.equal(a, b, msg)      → strict equality
  nc.assert.deepEqual(a, b, msg)  → JSON deep equality
  nc.assert.truthy(val, msg)      → truthy check
  nc.assert.includes(arr, item)   → array includes

TIPS:
  - nc_eval supports await: nc_eval("await nc.wait.ms(100); nc.node('x')")
  - For multi-statement code, just write statements — the bridge handles it
  - nc_run_test runs .ts files: export default async function() { ... }
  - Results must be JSON-serializable (no functions, DOM elements, etc.)
`.trim();
}

// ── Export ───────────────────────────────────────────────────────────────

export const nc = {
    node,
    nodes,
    dom,
    ui,
    configPanel,
    emit,
    send,
    run,
    agentChat,
    state: valtioState,
    assert,
    wait,
    help,
};
