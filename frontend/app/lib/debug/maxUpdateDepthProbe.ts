/* eslint-disable @typescript-eslint/no-explicit-any */
/**
 * DEV-only probe for React #185 ("Maximum update depth exceeded").
 *
 * Localizes a runaway synchronous commit loop BEFORE React throws, by counting
 * our own `onCommitFiberRoot` invocations as a faithful proxy for react-dom's
 * internal `nestedUpdateCount` (both run in the same synchronous `flushSpawnedWork`
 * cascade — verified against react-dom 19.1.1), tripping at 40 (React throws at
 * >50) while the loop's stack is still live, then dumping the offending fiber.
 *
 * It distinguishes the two #185 classes definitively: a callback-ref re-attach
 * loop (radix composeRefs/setRef churn — e.g. PopperContent's inline setContent
 * ref) populates `reports[]`; a setState-in-render/effect loop yields an explicit
 * "no churning ref" warning routing you to the breakpoint recipe.
 *
 * MUST be the first import in entry.client.tsx, above `react-dom/client`, so the
 * DevTools hook exists before react-dom's `injectInternals` reads it. No-ops
 * outside development (the install body is dead-code-eliminated in prod builds).
 */

// Dump well before React's >50 throw. Trip on >= (not ==): some loops throw
// during a ref-attach setState at ~39 commits, BEFORE the 40th commit's
// onCommitFiberRoot fires, so an exact ==40 check never matched and the probe
// silently missed the loop. 30 leaves margin to capture the live fiber tree.
const TRIP_AT = 30;
const OWNER_MAX = 30;
const HOOK_MAX = 64;
const TREE_MAX_NODES = 20000;
const CHANNEL_MAX = 1400; // nc channel clips at 1500; keep the pointer short

type Fiber = any;

/* React's getComponentNameFromFiber, transcribed for 19.1.1 dev fibers. */
function componentName(fiber: Fiber | null): string | null {
    if (!fiber) return null;
    const type = fiber.type;
    switch (fiber.tag) {
        case 5: case 26: case 27: return typeof type === 'string' ? type : 'Host';
        case 11: {
            const r = type?.render;
            const n = r?.displayName || r?.name || '';
            return type?.displayName || (n ? `ForwardRef(${n})` : 'ForwardRef');
        }
        case 16: return 'Lazy';
        case 10: return (type?.displayName || type?._context?.displayName || 'Context') + '.Provider';
        case 9: return (type?._context?.displayName || 'Context') + '.Consumer';
        case 3: return 'HostRoot';
        case 7: return 'Fragment';
        case 13: return 'Suspense';
        case 0: case 1: case 14: case 15:
            if (typeof type === 'function') return type.displayName || type.name || null;
            if (type && typeof type === 'object') return type.displayName || type.render?.name || type.type?.name || null;
            if (typeof type === 'string') return type;
            return null;
        default: return null;
    }
}

const isFunctionComponentTag = (tag: number) => tag === 0 || tag === 14 || tag === 15;
const isHostTag = (tag: number) => tag === 5 || tag === 26 || tag === 27;

function summarize(v: unknown, depth = 0): unknown {
    if (v == null || typeof v === 'number' || typeof v === 'boolean' || typeof v === 'string') return v;
    if (typeof v === 'function') return `[fn ${(v as any).name || 'anonymous'}]`;
    if (typeof Element !== 'undefined' && v instanceof Element) return `[Element <${v.tagName.toLowerCase()}>]`;
    if (depth > 2) return '[…]';
    if (Array.isArray(v)) return v.slice(0, 8).map((x) => summarize(x, depth + 1));
    try {
        const o: Record<string, unknown> = {};
        for (const k of Object.keys(v as object).slice(0, 16)) o[k] = summarize((v as any)[k], depth + 1);
        return o;
    } catch { return '[unserializable]'; }
}

/** JSX-creator chain (_debugOwner), the "who rendered this" path. */
function ownerChain(fiber: Fiber, max = OWNER_MAX): string[] {
    const out: string[] = [];
    let f: Fiber | null = fiber;
    const seen = new Set<Fiber>();
    while (f && !seen.has(f) && out.length < max) {
        seen.add(f);
        const n = componentName(f);
        if (n) out.push(n);
        f = f._debugOwner ?? null;
    }
    return out;
}

/** Structural mount path (return chain to root). */
function returnChain(fiber: Fiber, max = OWNER_MAX): string[] {
    const out: string[] = [];
    let f: Fiber | null = fiber;
    while (f && out.length < max) {
        const n = componentName(f);
        if (n) out.push(n);
        f = f.return ?? null;
    }
    return out;
}

/**
 * Enumerate the hook list. `queue.pending` is best-effort: it is usually already
 * consumed by the time we read at the commit boundary, so an empty
 * pendingHookIndexes does NOT exonerate a hook — the breakpoint recipe is the
 * authoritative culprit identifier.
 */
function describeHooks(fiber: Fiber): Array<{ index: number; hasQueue: boolean; hasPending: boolean }> {
    const hooks: Array<{ index: number; hasQueue: boolean; hasPending: boolean }> = [];
    let hook = fiber.memoizedState;
    let i = 0;
    const seen = new Set<any>();
    while (hook && !seen.has(hook) && i < HOOK_MAX) {
        seen.add(hook);
        if (hook && typeof hook === 'object' && 'memoizedState' in hook) {
            const q = hook.queue;
            hooks.push({ index: i, hasQueue: !!q, hasPending: !!(q && q.pending != null) });
        }
        hook = hook.next;
        i++;
    }
    return hooks;
}

function fiberFromDom(node: Element): Fiber | null {
    for (const k of Object.keys(node)) {
        if (k.startsWith('__reactFiber$')) return (node as any)[k] ?? null;
    }
    return null;
}

function refSource(ref: unknown): string {
    if (typeof ref !== 'function') return ref == null ? 'null' : `[ref object ${typeof ref}]`;
    try {
        const s = (ref as any).toString();
        return s.length > 300 ? s.slice(0, 300) + ' …' : s;
    } catch { return '[unprintable fn]'; }
}

/** Serializable identity of the offending DOM node — which on-screen element is
 *  looping. Captures tag + classes + aria/title + data-testid + visible text so
 *  the suspect is identifiable from the persisted log without a live fiber. */
function describeDom(el: unknown): string {
    if (typeof Element === 'undefined' || !(el instanceof Element)) return 'none';
    try {
        const tag = el.tagName.toLowerCase();
        const cls = (el.getAttribute('class') || '').slice(0, 140);
        const aria = el.getAttribute('aria-label') || el.getAttribute('title') || '';
        const tid = el.getAttribute('data-testid') || el.getAttribute('data-test') || '';
        const text = (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 50);
        return `<${tag}${tid ? ` data-testid="${tid}"` : ''}${aria ? ` aria-label="${aria}"` : ''}` +
            `${cls ? ` class="${cls}"` : ''}>${text}`;
    } catch { return '[undescribable element]'; }
}

function fingerprint(parts: string[]): string {
    const s = parts.join('|');
    let h = 5381;
    for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
    return 'fp_' + (h >>> 0).toString(36);
}

/** Host fibers whose callback `ref` identity differs from the alternate — the composeRefs/setRef churn signature. */
function findChurningRefFibers(root: Fiber, limit = 12): Fiber[] {
    const hits: Fiber[] = [];
    const start: Fiber | null = root.current ?? root;
    if (!start) return hits;
    const stack: Fiber[] = [start];
    const seen = new Set<Fiber>();
    let visited = 0;
    while (stack.length && hits.length < limit && visited < TREE_MAX_NODES) {
        const f = stack.pop();
        if (!f || seen.has(f)) continue;
        seen.add(f);
        visited++;
        if (isHostTag(f.tag) && typeof f.ref === 'function') {
            const altRef = f.alternate?.ref;
            if (altRef !== undefined && altRef !== f.ref) hits.push(f);
        }
        if (f.child) stack.push(f.child);
        if (f.sibling) stack.push(f.sibling);
    }
    return hits;
}

/** Nearest _debugOwner that is a function component holding a useState/useReducer hook. */
function nearestStatefulOwner(fiber: Fiber): Fiber | null {
    let f: Fiber | null = fiber;
    const seen = new Set<Fiber>();
    while (f && !seen.has(f)) {
        seen.add(f);
        if (isFunctionComponentTag(f.tag) && f.memoizedState && describeHooks(f).some((h) => h.hasQueue)) return f;
        f = f._debugOwner ?? null;
    }
    return null;
}

interface Report {
    fingerprint: string;
    suspectComponent: string | null;
    ownerChain: string[];
    returnChain: string[];
    hostElementTag: string | null;
    domDesc: string;
    refChanged: boolean;
    refSourceCurrent: string;
    refSourcePrev: string;
    pendingHookIndexes: number[];
    domNode: Element | null;
    memoizedProps: unknown;
}

function buildReports(root: Fiber): Report[] {
    const reports: Report[] = [];
    for (const hostFiber of findChurningRefFibers(root)) {
        const dom: Element | null = hostFiber.stateNode ?? null;
        const owner: Fiber | null = hostFiber._debugOwner ?? null;
        const suspect: Fiber | null = owner ? nearestStatefulOwner(owner) : null;
        const hooks = suspect ? describeHooks(suspect) : [];
        const hostName = componentName(hostFiber);
        reports.push({
            fingerprint: fingerprint([componentName(suspect) ?? '?', hostName ?? '?', refSource(hostFiber.ref)]),
            suspectComponent: componentName(suspect),
            ownerChain: owner ? ownerChain(owner) : [],
            returnChain: owner ? returnChain(owner) : [],
            hostElementTag: hostName,
            domDesc: describeDom(dom),
            refChanged: hostFiber.alternate?.ref !== hostFiber.ref,
            refSourceCurrent: refSource(hostFiber.ref),
            refSourcePrev: refSource(hostFiber.alternate?.ref),
            pendingHookIndexes: hooks.filter((h) => h.hasPending).map((h) => h.index),
            domNode: dom,
            memoizedProps: suspect ? summarize(suspect.memoizedProps) : undefined,
        });
    }
    return reports;
}

function dump(root: Fiber, count: number) {
    const reports = buildReports(root);
    const g = console.groupCollapsed?.bind(console) ?? console.log;
    g(`%c[#185 PROBE] ${count} nested sync commits on one root — dumping before React's >50 throw`,
        'color:#f00;font-weight:bold');

    if (reports.length === 0) {
        console.warn('[#185 PROBE] CLASS = setState-in-render/effect (NOT a composed-ref loop). ' +
            'No host callback-ref identity churn found. Use the breakpoint recipe: conditional ' +
            '`nestedUpdateCount > 40` at getRootForUpdatedFiber, then read the dispatching `fiber` + the ' +
            'hook whose `.queue === queue`. Prime suspect: a setState during render (see composeMessages #185).');
    }
    for (const r of reports) {
        console.log('%c— CLASS = composed-ref re-attach loop —', 'color:#f80;font-weight:bold', r.fingerprint);
        console.log('host element:', r.hostElementTag, r.domNode);
        console.log('ref source (current):', r.refSourceCurrent);
        console.log('ref source (prev):', r.refSourcePrev, ' identity changed:', r.refChanged);
        console.log('%csuspect (dispatches setState via the churning ref):', 'color:#0a0;font-weight:bold', r.suspectComponent);
        console.log('  owner chain (JSX creators → root):', r.ownerChain.join(' < '));
        console.log('  structural chain (return → root):', r.returnChain.join(' < '));
        console.log('  pending hook indexes (best-effort):', r.pendingHookIndexes);
        console.log('  memoizedProps:', r.memoizedProps);
    }
    console.trace('[#185 PROBE] commit stack at trip point');
    console.groupEnd?.();

    const top = reports[0];

    // VISIBLE one-liner (outside the collapsed group) so the culprit is obvious
    // in a pasted console without expanding anything.
    if (top) {
        console.error(
            `%c[#185] RENDER LOOP → ${top.domDesc}\n` +
            `  rendered by: ${top.ownerChain.slice(0, 8).join(' < ')}\n` +
            `  setState dispatcher (suspect): ${top.suspectComponent}\n` +
            `  full report: window.__react185  |  history: sessionStorage.__react185_log`,
            'color:#f00;font-weight:bold',
        );
    } else {
        console.error('[#185] RENDER LOOP (setState-in-render/effect — no churning ref). See window.__react185.');
    }

    try {
        (window as any).__react185 = { tripped: true, count, reports, root, at: new Date().toISOString() };
    } catch { /* noop */ }

    // Persist a serializable snapshot to sessionStorage so the report SURVIVES
    // the error-boundary recreate and a manual reload — read it after the fact
    // via sessionStorage.__react185_log (window.__react185 is wiped on reload).
    try {
        const serializable = reports.map((r) => ({
            domDesc: r.domDesc,
            hostElementTag: r.hostElementTag,
            suspectComponent: r.suspectComponent,
            refChanged: r.refChanged,
            refSourceCurrent: r.refSourceCurrent,
            refSourcePrev: r.refSourcePrev,
            ownerChain: r.ownerChain,
            returnChain: r.returnChain,
            pendingHookIndexes: r.pendingHookIndexes,
            memoizedProps: r.memoizedProps,
            fingerprint: r.fingerprint,
        }));
        const klass = top ? 'ref-loop' : 'setState-in-render';
        const prev = JSON.parse(sessionStorage.getItem('__react185_log') || '[]');
        prev.push({ at: new Date().toISOString(), count, klass, url: location.pathname, reports: serializable });
        sessionStorage.setItem('__react185_log', JSON.stringify(prev.slice(-8)));
    } catch { /* noop — sessionStorage full/blocked */ }

    try {
        void import('~/lib/nc/channel').then(({ channel }) => {
            const msg = (top
                ? `[#185] ${count} nested commits. CLASS=ref-loop suspect=${top.suspectComponent} ` +
                  `dom=${top.domDesc} refChanged=${top.refChanged} fp=${top.fingerprint}\n` +
                  `owner: ${top.ownerChain.join(' < ')}\nrefCur: ${top.refSourceCurrent}`
                : `[#185] ${count} nested commits. CLASS=setState-in-render/effect (no churning ref). ` +
                  `Use breakpoint recipe; suspect composeMessages-style render loop.`
            ).slice(0, CHANNEL_MAX);
            channel.error(msg, {
                source: 'react185-probe',
                klass: top ? 'ref-loop' : 'setState-in-render',
                component: top?.suspectComponent ?? 'unknown',
                fingerprint: top?.fingerprint ?? 'none',
            });
        }).catch(() => { /* noop */ });
    } catch { /* noop */ }
}

export function installMaxUpdateDepthProbe() {
    if (process.env.NODE_ENV !== 'development') return;
    if (typeof window === 'undefined') return;

    const HOOK_KEY = '__REACT_DEVTOOLS_GLOBAL_HOOK__';
    const w = window as any;

    // Hook object must EXIST before react-dom's injectInternals runs, else React
    // never calls onCommitFiberRoot. Synthesize a minimal one only if absent
    // (the real DevTools extension, when present, owns it — we just wrap it).
    if (!w[HOOK_KEY]) {
        w[HOOK_KEY] = {
            isDisabled: false,
            supportsFiber: true,
            renderers: new Map(),
            inject() { return 1; },
            onCommitFiberRoot() {},
            onCommitFiberUnmount() {},
            onPostCommitFiberRoot() {},
            checkDCE() {},
            setStrictMode() {},
        };
    }
    const hook = w[HOOK_KEY];
    // Version marker — lets a debugging session confirm the persist-capable probe
    // is actually loaded (bump on capture-behavior changes).
    w.__react185_probeVersion = 'v3-stack-backstop';

    // Backstop capture, INDEPENDENT of the commit-counter fiber walk below (which
    // can miss when a loop unwinds before the counter trips). React (dev) and
    // React Router log the error WITH its component stack via console.error when
    // an error boundary catches it; grab that stack into sessionStorage so #185
    // is captured even when the fiber probe doesn't fire.
    if (!w.__react185_consoleHooked) {
        w.__react185_consoleHooked = true;
        const orig = console.error.bind(console);
        console.error = (...args: any[]) => {
            try {
                let componentStack = '';
                const parts: string[] = [];
                for (const a of args) {
                    if (a && typeof a === 'object') {
                        const cs = (a as any).componentStack || (a as any).errorInfo?.componentStack;
                        if (typeof cs === 'string') componentStack = cs;
                        parts.push(a instanceof Error ? (a.message || '') : ((): string => { try { return String(a); } catch { return '[obj]'; } })());
                    } else {
                        parts.push(String(a));
                    }
                }
                const joined = parts.join(' ');
                if (/Maximum update depth exceeded|above error occurred in|caught the following error/i.test(joined)) {
                    const prev = JSON.parse(sessionStorage.getItem('__react185_consoleStack') || '[]');
                    prev.push({ at: new Date().toISOString(), msg: joined.slice(0, 500), componentStack: componentStack.slice(0, 3000) });
                    sessionStorage.setItem('__react185_consoleStack', JSON.stringify(prev.slice(-8)));
                }
            } catch { /* noop */ }
            return orig(...args);
        };
    }

    if (hook.__maxDepthProbeInstalled) return;
    hook.__maxDepthProbeInstalled = true;

    const counts = new WeakMap<Fiber, number>();
    let lastRoot: Fiber | null = null;
    let scheduled = false;
    const trippedThisBurst = new WeakSet<Fiber>();

    const resetSoon = () => {
        if (scheduled) return;
        scheduled = true;
        // The whole nested cascade is synchronous, so this microtask drains only
        // AFTER a real loop has reached TRIP_AT — a legit burst (<40) resets clean.
        queueMicrotask(() => {
            scheduled = false;
            if (lastRoot) { counts.set(lastRoot, 0); trippedThisBurst.delete(lastRoot); }
        });
    };

    const prevRoot = hook.onCommitFiberRoot?.bind(hook);
    hook.onCommitFiberRoot = (id: any, root: Fiber, prio: any, didError: any) => {
        lastRoot = root;
        const c = (counts.get(root) ?? 0) + 1;
        counts.set(root, c);
        if (c >= TRIP_AT && !trippedThisBurst.has(root)) {
            trippedThisBurst.add(root); // dump once per synchronous burst; resetSoon clears it after
            try { dump(root, c); } catch (e) { console.warn('[#185 PROBE] dump failed', e); }
        }
        resetSoon();
        if (prevRoot) { try { prevRoot(id, root, prio, didError); } catch { /* keep extension alive */ } }
    };

    console.info('[#185 PROBE] installed (DEV). Trip at', TRIP_AT, 'nested commits/root. Inspect window.__react185 after a trip.');
}

installMaxUpdateDepthProbe();
