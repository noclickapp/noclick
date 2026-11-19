// Your sections of a space's channels, kept for you on the server (GET/PUT /v1/channels/sections) so they follow you to
// every device, and followed live: a `sections` frame says your layout moved (another device saved it) and it's read
// again. A change shows at once and saves behind it, one save at a time, each naming the version it was made on; a
// save that loses to a newer one is made again on what's kept, so no device's change overwrites another's.
import { useCallback, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { errorText } from '@/screens/console/pages/resources/shared';
import { Channel as PlatformChannel, Conflict, type ChannelSections, type NoClick } from 'noclick';
import { useWorkV1 } from '../agents/reads';
import { useWorkClient } from '../client';
import { useWorkFrames } from '@/sdk/live';
import { EMPTY_LAYOUT, type BuiltInList, type Layout, type LayoutChange } from './sections';

/** Saves that lose to newer ones in a row before the change is given up. */
const MAX_REBASES = 3;

const layoutOf = (read: ChannelSections): Layout => ({
    version: read.version,
    sections: read.sections.map((s) => ({ id: s.id, name: s.name, folded: s.folded, channelIds: [...s.channelIds] })),
    folded: read.folded.filter((k): k is BuiltInList => k === 'starred' || k === 'channels'),
});

export const sectionsKey = (workspaceId: string | null) => `work:sections:${workspaceId ?? 'none'}`;

export const readSections = async (client: NoClick, workspaceId: string | null) => layoutOf(await PlatformChannel.sections({ client, user: null, workspace: workspaceId ?? undefined }));

const saveSections = async (client: NoClick, workspaceId: string | null, layout: Layout, version: number) =>
    layoutOf(await PlatformChannel.saveSections({ version, sections: layout.sections, folded: layout.folded }, { client, user: null, workspace: workspaceId ?? undefined }));

export interface ChannelSectionsState {
    layout: Layout;
    /** Read at least once (else the layout is empty only because it isn't in yet). */
    ready: boolean;
    change(change: LayoutChange): void;
}

export function useChannelSections(workspaceId: string | null): ChannelSectionsState {
    const client = useWorkClient();
    const key = sectionsKey(workspaceId);
    const read = useWorkV1(key, (c) => readSections(c, workspaceId));
    const { refresh, mutate } = read;
    // Changes not yet saved, shown over the last layout the server answered.
    const [pending, setPending] = useState<LayoutChange[]>([]);
    const s = useRef({ key, base: read.data ?? EMPTY_LAYOUT, queue: [] as LayoutChange[], saving: false, rebases: 0, stale: false });
    if (s.current.key !== key) s.current = { key, base: read.data ?? EMPTY_LAYOUT, queue: [], saving: false, rebases: 0, stale: false };
    // While nothing's on its way, the server's answer is the base.
    if (!s.current.saving && !s.current.queue.length && read.data) s.current.base = read.data;

    useWorkFrames('platform:channel', (frame) => {
        if (frame.kind !== 'sections' || (frame.workspace_id ?? null) !== workspaceId) return;
        // Mid-save, the save itself learns of it (it loses and is made again on what's kept): read it after.
        if (s.current.saving) s.current.stale = true;
        else void refresh();
    });

    const flush = useCallback(async () => {
        const state = s.current;
        if (state.saving || !state.queue.length) return;
        state.saving = true;
        const taken = state.queue.length;
        const next = state.queue.reduce((layout, change) => change(layout), state.base);
        try {
            const saved = await saveSections(client, workspaceId, next, state.base.version);
            if (s.current !== state) return;
            state.base = saved;
            state.queue = state.queue.slice(taken);
            state.rebases = 0;
            mutate(saved);
        } catch (e) {
            if (s.current !== state) return;
            if (e instanceof Conflict && state.rebases < MAX_REBASES) {
                // Another device saved first: the same changes, made again on what it kept.
                state.rebases += 1;
                try {
                    state.base = await readSections(client, workspaceId);
                } catch (readError) {
                    state.queue = [];
                    toast.error('Couldn’t save your sections', { description: errorText(readError) });
                }
            } else {
                state.queue = state.queue.slice(taken);
                state.rebases = 0;
                toast.error('Couldn’t save your sections', { description: errorText(e) });
                void refresh();
            }
        } finally {
            if (s.current === state) {
                state.saving = false;
                setPending([...state.queue]);
                if (state.queue.length) void flush();
                else if (state.stale) {
                    state.stale = false;
                    void refresh();
                }
            }
        }
    }, [client, workspaceId, mutate, refresh]);

    const change = useCallback(
        (one: LayoutChange) => {
            s.current.queue.push(one);
            setPending([...s.current.queue]);
            void flush();
        },
        [flush]
    );

    const base = s.current.saving || pending.length ? s.current.base : (read.data ?? EMPTY_LAYOUT);
    const layout = useMemo(() => pending.reduce((l, c) => c(l), base), [pending, base]);
    return { layout, ready: read.data !== undefined || !!read.error, change };
}
