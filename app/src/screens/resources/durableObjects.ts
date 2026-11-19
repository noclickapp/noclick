// How an app's Durable Object classes read on its page in Resources and in the console's app drawer
// (GET /v1/projects/{id}/durable_objects): where each lives, what it holds, where it stands, and how deleting one is
// previewed and done. A figure the platform couldn't read says so; it's never shown as nothing.
import type { DeletionImpact, Removal } from './platform';
import type { DurableObjectClass, Project } from 'noclick';
import { formatMoney } from '@/screens/console/lib/format';

export type DeletePreview = (path: string, user: string | null) => Promise<DeletionImpact>;

/** Takes a trash entry back (`POST /v1/trash/{id}/restore`), acting for `user` (null: the account). */
export type TrashRestore = (trashId: string, user: string | null) => Promise<void>;

/** Where the class's objects live: production, or one preview branch. */
export function environmentText(cls: DurableObjectClass): string {
    return cls.environment === 'production' ? 'Production' : `Preview · ${cls.branch ?? 'branch'}`;
}

/** How many objects it has, "1,000+" past what was counted, "Unknown" when the platform couldn't say. */
export function objectsText(cls: DurableObjectClass): string {
    if (cls.objectsCount == null) return 'Unknown';
    const counted = cls.objectsCount.toLocaleString('en-US');
    return `${counted}${cls.objectsMore ? '+' : ''} ${cls.objectsCount === 1 && !cls.objectsMore ? 'object' : 'objects'}`;
}

/** What its objects store, as the platform last reported it. */
export function storedText(bytes: number | null): string {
    if (bytes == null) return 'Unknown';
    if (bytes < 1024) return `${bytes} B`;
    const units = ['KB', 'MB', 'GB'];
    let value = bytes / 1024;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
        value /= 1024;
        unit += 1;
    }
    return `${value >= 10 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

const STOPPED_BECAUSE = { trash: 'the app is in the trash', budget: 'the app reached its spending limit' } as const;

function dayText(at: Date | null): string | null {
    return at ? at.toLocaleDateString('en-US', { month: 'long', day: 'numeric', timeZone: 'UTC' }) : null;
}

/** Where the class stands, in words, and whether that needs attention. */
export function statusText(cls: DurableObjectClass): { words: string; detail: string | null; attention: boolean } {
    switch (cls.status) {
        case 'trashed': {
            const until = dayText(cls.restorableUntil);
            return { words: 'In the trash', detail: until ? `Restorable until ${until}, with its data` : 'Restorable from the trash, with its data', attention: true };
        }
        case 'parked':
            return { words: 'Parked', detail: 'Kept with its data; no release that serves exports it', attention: true };
        case 'stopped':
            return {
                words: 'Stopped',
                detail: `Kept with its data: ${cls.stoppedFor ? STOPPED_BECAUSE[cls.stoppedFor] : 'its objects are stopped'}`,
                attention: true,
            };
        default:
            return { words: 'Live', detail: null, attention: false };
    }
}

/** What the app's Durable Objects were charged this month, every environment's together; said to be unknown, never
 * $0, when the platform didn't say. */
export function costText(cost: { usd: number } | null): string {
    return cost ? `${formatMoney(cost.usd)} this month` : 'Cost unknown';
}

/** How a class is deleted, the way the platform API does: to the trash for 30 days, its objects and data kept until
 * then, previewed first (`POST /v1/delete_previews`). Null for one already in the trash. */
/** How a class in the trash comes back, with its objects and their data. Null for one that isn't there. */
export function classRestore(project: Project, cls: DurableObjectClass, restore: TrashRestore): (() => Promise<string>) | null {
    const trashId = cls.trashId;
    if (cls.status !== 'trashed' || !trashId) return null;
    return async () => {
        await restore(trashId, project.userId ?? null);
        return `Restored ${cls.name} with its data`;
    };
}

export function classRemoval(project: Project, cls: DurableObjectClass, preview: DeletePreview, onDone: () => void): Removal | null {
    if (cls.status === 'trashed') return null;
    const where = cls.environment === 'production' ? '' : ` from the ${cls.branch} preview`;
    return {
        label: 'Delete',
        confirm: `Move ${cls.name}${where} to the trash`,
        preview: () => preview(`/v1/projects/${project.id}/durable_objects/${cls.id}`, project.userId ?? null),
        run: async () => {
            await cls.delete();
            onDone();
            return { done: `Moved ${cls.name} to the trash`, gone: false };
        },
    };
}
