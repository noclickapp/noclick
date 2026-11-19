// An app's Durable Object classes (GET /v1/projects/{id}/durable_objects), on its page in Resources and in the
// console's app drawer: each class in each environment with its objects, what they store and where it stands, what
// the app's objects cost this month, and Delete, which moves a class to the trash through the platform's own preview.
// An app that declares none shows nothing.
import { useCallback, useState } from 'react';
import { toast } from 'sonner';
import { BUTTON_SECONDARY } from '@/ui/buttons';
import { usePlatformResources, type Removal } from './platform';
import { RemovalPanel, Section, Surface } from './ui';
import { cn } from '@/ui/utils';
import { useV1, type V1State } from '@/sdk/useV1';
import type { DurableObjectClass, DurableObjectClasses, Project } from 'noclick';
import { errorText } from '@/screens/console/pages/resources/shared';
import {
    classRemoval,
    classRestore,
    costText,
    environmentText,
    objectsText,
    statusText,
    storedText,
    type DeletePreview,
    type TrashRestore,
} from './durableObjects';
import { Pending, ROW } from './parts';

/** The read both surfaces share: a deploy's frame re-reads it in either (`resources:projects…`, `projects/{id}/…`). */
export function useDurableObjects(project: Project, prefix: 'resources:' | '' = ''): V1State<DurableObjectClasses> {
    return useV1(`${prefix}projects/${project.id}/durable_objects`, () => project.durableObjects());
}

function ClassRow({
    cls,
    unread,
    onDelete,
    onRestore,
}: {
    cls: DurableObjectClass;
    unread: readonly string[];
    onDelete: (() => void) | null;
    onRestore: (() => Promise<void>) | null;
}) {
    const [restoring, setRestoring] = useState(false);
    const status = statusText(cls);
    return (
        <div className={cn(ROW, 'flex-wrap')} data-testid="durable-object-class">
            <span className="min-w-0 flex-1 basis-56">
                <span className="block truncate text-[14px] text-foreground">
                    {cls.name}
                    {cls.binding && <span className="ml-2 font-mono text-[12px] text-muted-foreground">env.{cls.binding}</span>}
                </span>
                <span className="block text-[12.5px] text-muted-foreground">
                    {environmentText(cls)} · {unread.includes('objects') ? 'Objects unknown' : objectsText(cls)} ·{' '}
                    {unread.includes('stored_bytes') ? 'Storage unknown' : storedText(cls.storedBytes)}
                </span>
                {status.detail && <span className="block text-[12.5px] text-muted-foreground">{status.detail}</span>}
            </span>
            <span className="flex w-full items-center justify-between gap-3 sm:w-auto sm:shrink-0">
                <span data-testid="durable-object-status" className={cn('text-[12.5px]', status.attention ? 'text-amber-700 dark:text-amber-400' : 'text-foreground/85')}>
                    {status.words}
                </span>
                {onDelete && (
                    <button type="button" className={cn(BUTTON_SECONDARY, 'hover:text-red-600 dark:hover:text-red-400')} onClick={onDelete}>
                        Delete
                    </button>
                )}
                {onRestore && (
                    <button
                        type="button"
                        className={BUTTON_SECONDARY}
                        disabled={restoring}
                        onClick={() => {
                            setRestoring(true);
                            void onRestore().finally(() => setRestoring(false));
                        }}
                    >
                        {restoring ? 'Restoring…' : 'Restore'}
                    </button>
                )}
            </span>
        </div>
    );
}

/** The classes as rows, with a class's deletion asked in place under them, and one in the trash restored in its row. */
export function DurableObjectsList({
    project,
    read,
    preview,
    restore,
}: {
    project: Project;
    read: V1State<DurableObjectClasses>;
    preview: DeletePreview;
    restore: TrashRestore;
}) {
    const [removing, setRemoving] = useState<{ id: string; removal: Removal } | null>(null);
    const classes = read.data;
    if (!classes) return <Pending read={read} rows={2} />;
    return (
        <>
            <Surface>
                {classes.map((cls) => {
                    const removal = classRemoval(project, cls, preview, () => void read.refresh());
                    const back = classRestore(project, cls, restore);
                    return (
                        <ClassRow
                            key={cls.id}
                            cls={cls}
                            unread={classes.unread}
                            onDelete={removal && !removing ? () => setRemoving({ id: cls.id, removal }) : null}
                            onRestore={
                                back &&
                                (async () => {
                                    try {
                                        toast(await back());
                                        await read.refresh();
                                    } catch (error) {
                                        toast.error(errorText(error));
                                    }
                                })
                            }
                        />
                    );
                })}
            </Surface>
            {removing && (
                <RemovalPanel
                    removal={removing.removal}
                    onCancel={() => setRemoving(null)}
                    onDone={(result) => {
                        setRemoving(null);
                        toast(result.done);
                    }}
                />
            )}
        </>
    );
}

/** The section on an app's page in Resources; nothing for an app that declares no Durable Objects. */
export function AppDurableObjects({ project, preview }: { project: Project; preview: DeletePreview }) {
    const read = useDurableObjects(project, 'resources:');
    const platform = usePlatformResources();
    // Through Resources' own restore, which reads its trash and every list again.
    const restore = useCallback<TrashRestore>(
        async (id, user) => {
            if (!platform) throw new Error('Restoring needs the platform, which isn’t here.');
            await platform.restore({ id, name: id, trashedAt: null, purgeAfter: null, ...(user ? { owner: { id: user, name: user } } : {}) });
        },
        [platform]
    );
    const classes = read.data;
    if (classes && classes.length === 0) return null;
    if (!classes && read.error === undefined) return null; // nothing to say until it's known the app has any
    return (
        <Section title="Durable Objects" meta={classes ? costText(classes.cost) : null}>
            <DurableObjectsList project={project} read={read} preview={preview} restore={restore} />
        </Section>
    );
}
