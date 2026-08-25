/* Server-backed authoring state for the Test Run screen: custom test runs,
   run names, and staged-message edits. This is CONTENT, not UI state — it
   belongs to the workflow, not the browser — so it persists in
   workflows.settings.rehearsal_authoring (shallow-merged on write, immune to
   the graph autosave's blob replacement) and rides forks: a template ships
   its test suite.

   A module-level valtio store keyed by workflow gives the same
   survive-tab-switches behavior the old cached store had; each workflow
   hydrates from the server once per session and writes through debounced.
   The bench ('bench' scope) stays purely local — fixtures never sync. */

import { useCallback, useEffect } from 'react';
import { proxy, useSnapshot } from 'valtio';
import { sendEventAsync } from '~/lib/socket-sender';
import type { LeadPatch } from './native';
import type { MockRun, TriggerFixture } from './fixture';

export interface CustomRunAuthoring {
    slug: string;
    backendKey?: string;
    lead: MockRun['lead'];
}

export interface RehearsalAuthoring {
    runs: Record<string, CustomRunAuthoring[]>;
    names: Record<string, string>;
    edits: Record<string, LeadPatch>;
    /** Registry situations removed from THIS workflow (keys `${trigger}:${slug}`).
        Built-ins are deletable defaults, not fixtures — but they're derived,
        not stored, so deletion is an overlay. */
    hidden: string[];
}

interface AuthoringSlot extends RehearsalAuthoring {
    /** Server hydration finished (or was skipped for the bench). */
    loaded: boolean;
}

const EMPTY: RehearsalAuthoring = { runs: {}, names: {}, edits: {}, hidden: [] };

const store = proxy<{ byScope: Record<string, AuthoringSlot> }>({ byScope: {} });
const hydrating = new Set<string>();
const pushTimers = new Map<string, number>();

function slotFor(scope: string): AuthoringSlot {
    if (!store.byScope[scope]) {
        store.byScope[scope] = { ...structuredClone(EMPTY), loaded: scope === 'bench' };
    }
    return store.byScope[scope];
}

/** The authoring overlay applied to the live trigger list: renames on
    registry situations, custom runs appended. ONE implementation — the Test
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

/** Re-fetch authoring from the server, discarding the once-per-session latch.
    Used when the server content changed underneath us — the AI builder just
    authored a test run — so the screen can select it by slug. */
export async function rehydrateRehearsalAuthoring(workflowId: string): Promise<void> {
    hydrating.delete(workflowId);
    await hydrate(workflowId);
}

async function hydrate(workflowId: string): Promise<void> {
    if (hydrating.has(workflowId)) return;
    hydrating.add(workflowId);
    try {
        const res: any = await sendEventAsync({
            event_name: 'workflow:get',
            workflow_id: workflowId,
        } as any);
        const saved = res?.workflow?.settings?.rehearsal_authoring;
        const slot = slotFor(workflowId);
        if (saved && typeof saved === 'object') {
            // Server state wins over anything typed before hydration finished —
            // hydration races only the first seconds of a fresh session.
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

function schedulePush(workflowId: string): void {
    const prev = pushTimers.get(workflowId);
    if (prev) window.clearTimeout(prev);
    pushTimers.set(
        workflowId,
        window.setTimeout(() => {
            pushTimers.delete(workflowId);
            const slot = store.byScope[workflowId];
            if (!slot) return;
            void sendEventAsync({
                event_name: 'workflow:update',
                workflow_id: workflowId,
                settings: {
                    rehearsal_authoring: {
                        runs: JSON.parse(JSON.stringify(slot.runs)),
                        names: JSON.parse(JSON.stringify(slot.names)),
                        edits: JSON.parse(JSON.stringify(slot.edits)),
                        hidden: [...slot.hidden],
                    },
                },
            } as any).catch((e) => {
                // Owner-only gate: a collaborator's authoring stays session-local
                // rather than erroring their screen.
                console.warn('[rehearsal] authoring persist failed:', e);
            });
        }, 800)
    );
}

export function useRehearsalAuthoring(scope: string) {
    const isLive = scope !== 'bench';
    useEffect(() => {
        slotFor(scope);
        if (isLive) void hydrate(scope);
    }, [scope, isLive]);

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
