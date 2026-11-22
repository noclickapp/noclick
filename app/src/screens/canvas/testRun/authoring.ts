/* The Test Run screen's authoring state: the workflow's own test runs, the names it gave runs, its edits to staged
   messages, and the offered situations it removed. This is CONTENT, not UI state: it belongs to the workflow, not
   the browser, so it's kept with the workflow (its `rehearsal_authoring` setting, through the screen's host:
   `TEST_RUN.authoring`) and goes with a copy of it: a template ships its test suite.

   A module-level store keyed by workflow survives the screen being drawn again; each workflow is read once per
   session and written back debounced. The bench ('bench' scope) stays purely local: fixtures never sync. */

import { useCallback, useEffect } from 'react';
import type { NoClick } from 'noclick';
import { proxy, useSnapshot } from 'valtio';
import { useProvidedClient } from '@/sdk/client';
import { standing } from '@/slots';
import type { LeadPatch } from './native';
import type { MockRun, TriggerFixture } from './scenarios';
import { TEST_RUN } from '../slots';

export interface CustomRunAuthoring {
    slug: string;
    backendKey?: string;
    lead: MockRun['lead'];
}

export interface RehearsalAuthoring {
    runs: Record<string, CustomRunAuthoring[]>;
    names: Record<string, string>;
    edits: Record<string, LeadPatch>;
    /** Offered situations removed from THIS workflow (keys `${trigger}:${slug}`).
        Built-ins are deletable defaults, not fixtures — but they're derived,
        not stored, so deletion is an overlay. */
    hidden: string[];
}

interface AuthoringSlot extends RehearsalAuthoring {
    /** The read from the workflow finished (or was skipped for the bench). */
    loaded: boolean;
}

const EMPTY: RehearsalAuthoring = { runs: {}, names: {}, edits: {}, hidden: [] };

const store = proxy<{ byScope: Record<string, AuthoringSlot> }>({ byScope: {} });
const hydrating = new Set<string>();
const pushTimers = new Map<string, number>();
/** Each workflow's write under way, so a run that plays what's saved can wait for it. */
const writing = new Map<string, Promise<void>>();
/** The client the screen was last drawn with, for a host whose reads and writes are the API's. */
let client: NoClick | null = null;

function slotFor(scope: string): AuthoringSlot {
    if (!store.byScope[scope]) {
        store.byScope[scope] = { ...structuredClone(EMPTY), loaded: scope === 'bench' };
    }
    return store.byScope[scope];
}

/** The authoring overlay applied to the offered trigger list: renames on
    offered situations, custom runs appended. ONE implementation — the Test
    Run screen and the Setup preview must offer identical situations. */
export function withAuthoredRuns(
    baseTriggers: TriggerFixture[],
    runs: RehearsalAuthoring['runs'],
    names: RehearsalAuthoring['names'],
    hidden: RehearsalAuthoring['hidden'] = []
): TriggerFixture[] {
    return baseTriggers.map((t) => ({
        ...t,
        mocks: [
            ...t.mocks
                .filter((m) => !hidden.includes(`${t.slug}:${m.slug}`))
                .map((m) => {
                    const name = names[`${t.slug}:${m.slug}`];
                    return name ? { ...m, name } : m;
                }),
            ...(runs[t.slug] ?? []).map((c) => ({
                slug: c.slug,
                backendKey: c.backendKey,
                name: names[`${t.slug}:${c.slug}`] ?? 'Test run',
                lead: c.lead,
                events: [],
                doneAt: 0,
                artifacts: null,
                custom: true,
            })),
        ],
    }));
}

/** Read the authoring again from the workflow, discarding the once-per-session latch.
    Used when it changed underneath us (the builder just authored a test run),
    so the screen can select it by slug. */
export async function rehydrateRehearsalAuthoring(workflowId: string): Promise<void> {
    hydrating.delete(workflowId);
    await hydrate(workflowId);
}

async function hydrate(workflowId: string): Promise<void> {
    if (hydrating.has(workflowId)) return;
    hydrating.add(workflowId);
    try {
        const saved = await standing(TEST_RUN).authoring.read(workflowId, client);
        const slot = slotFor(workflowId);
        if (saved && typeof saved === 'object') {
            // What the workflow holds wins over anything typed before the read finished —
            // the read races only the first seconds of a fresh session.
            slot.runs = saved.runs && typeof saved.runs === 'object' ? saved.runs : {};
            slot.names = saved.names && typeof saved.names === 'object' ? saved.names : {};
            slot.edits = saved.edits && typeof saved.edits === 'object' ? saved.edits : {};
            slot.hidden = Array.isArray(saved.hidden) ? saved.hidden : [];
        }
        slot.loaded = true;
    } catch (e) {
        // Leave the slot usable locally; the next mount retries.
        console.error('[rehearsal] authoring hydrate failed:', e);
        hydrating.delete(workflowId);
    }
}

function push(workflowId: string): void {
    const slot = store.byScope[workflowId];
    if (!slot) return;
    const write = standing(TEST_RUN)
        .authoring.write(
            workflowId,
            {
                runs: JSON.parse(JSON.stringify(slot.runs)),
                names: JSON.parse(JSON.stringify(slot.names)),
                edits: JSON.parse(JSON.stringify(slot.edits)),
                hidden: [...slot.hidden],
            },
            client
        )
        .catch((e: unknown) => {
            // Only the workflow's owner writes it: someone else's authoring stays
            // session-local rather than erroring their screen.
            console.warn('[rehearsal] authoring persist failed:', e);
        })
        .finally(() => {
            if (writing.get(workflowId) === write) writing.delete(workflowId);
        });
    writing.set(workflowId, write);
}

function schedulePush(workflowId: string): void {
    const prev = pushTimers.get(workflowId);
    if (prev) window.clearTimeout(prev);
    pushTimers.set(
        workflowId,
        window.setTimeout(() => {
            pushTimers.delete(workflowId);
            push(workflowId);
        }, 800)
    );
}

/** Settles once the workflow holds the screen's authoring: a change still waiting is written now, and a write under
    way is waited for. For a host whose runs play what the workflow holds (`TEST_RUN.runsSaved`). */
export async function whenAuthoringSaved(workflowId: string): Promise<void> {
    const waiting = pushTimers.get(workflowId);
    if (waiting) {
        window.clearTimeout(waiting);
        pushTimers.delete(workflowId);
        push(workflowId);
    }
    await writing.get(workflowId);
}

/** Forgets every workflow's authoring held here, with any write still waiting: what the page starts with. */
export function forgetAuthoring(): void {
    for (const timer of pushTimers.values()) window.clearTimeout(timer);
    pushTimers.clear();
    writing.clear();
    hydrating.clear();
    for (const scope of Object.keys(store.byScope)) delete store.byScope[scope];
}

export function useRehearsalAuthoring(scope: string) {
    const isLive = scope !== 'bench';
    const provided = useProvidedClient();
    useEffect(() => {
        if (provided) client = provided;
        slotFor(scope);
        if (isLive) void hydrate(scope);
    }, [scope, isLive, provided]);

    const snap = useSnapshot(store);
    const slot = snap.byScope[scope];

    const mutate = useCallback(
        (fn: (draft: AuthoringSlot) => void) => {
            fn(slotFor(scope));
            if (isLive) schedulePush(scope);
        },
        [scope, isLive]
    );

    return {
        loaded: slot?.loaded ?? false,
        runs: (slot?.runs ?? EMPTY.runs) as RehearsalAuthoring['runs'],
        names: (slot?.names ?? EMPTY.names) as RehearsalAuthoring['names'],
        edits: (slot?.edits ?? EMPTY.edits) as RehearsalAuthoring['edits'],
        hidden: (slot?.hidden ?? EMPTY.hidden) as RehearsalAuthoring['hidden'],
        setRuns: (updater: (prev: RehearsalAuthoring['runs']) => RehearsalAuthoring['runs']) =>
            mutate((d) => {
                d.runs = updater(JSON.parse(JSON.stringify(d.runs)));
            }),
        setNames: (updater: (prev: RehearsalAuthoring['names']) => RehearsalAuthoring['names']) =>
            mutate((d) => {
                d.names = updater(JSON.parse(JSON.stringify(d.names)));
            }),
        setEdits: (updater: (prev: RehearsalAuthoring['edits']) => RehearsalAuthoring['edits']) =>
            mutate((d) => {
                d.edits = updater(JSON.parse(JSON.stringify(d.edits)));
            }),
        setHidden: (updater: (prev: RehearsalAuthoring['hidden']) => RehearsalAuthoring['hidden']) =>
            mutate((d) => {
                d.hidden = updater([...(d.hidden ?? [])]);
            }),
    };
}
