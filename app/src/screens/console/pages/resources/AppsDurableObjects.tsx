// The console app drawer's Durable Objects, after its bindings: the same list as the app's page in Resources
// (screens/resources/AppDurableObjects), read with the console's own client, its deletion previewed through
// POST /v1/delete_previews as Resources previews it. An app that declares none shows nothing.
import { useMemo } from 'react';
import { TrashItem, type Project } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import { DurableObjectsList, useDurableObjects } from '@/screens/resources/AppDurableObjects';
import { costText, type DeletePreview, type TrashRestore } from '@/screens/resources/durableObjects';
import type { DeletionImpact } from '@/screens/resources/platform';
import { useConsole } from '../../hooks/useConsole';
import { Section } from './shared';

export function AppDurableObjectsSection({ project }: { project: Project }) {
    const { client } = useConsole();
    const read = useDurableObjects(project);
    const preview = useMemo<DeletePreview>(
        () => async (path, user) =>
            (await client.request<{ impact: DeletionImpact }>('POST', '/v1/delete_previews', { json: { method: 'DELETE', path }, user })).impact,
        [client]
    );
    const restore = useMemo<TrashRestore>(
        () => async (id, user) => {
            await TrashItem.fromId(id, { client, user }).restore();
            invalidateV1('trash?');
        },
        [client]
    );
    const classes = read.data;
    if (!classes ? read.error === undefined : classes.length === 0) return null;
    const cost = classes ? costText(classes.cost) : null;
    return (
        <Section
            title={
                <span className="flex items-baseline gap-2">
                    Durable Objects{cost && <span className="text-[12px] font-normal tabular-nums text-muted-foreground">{cost}</span>}
                </span>
            }
        >
            <p className="m-0 mb-2 text-[12px] text-muted-foreground">Each class its code declares, in each environment. Their data survives releases; deleting a class moves it to the trash for 30 days.</p>
            <DurableObjectsList project={project} read={read} preview={preview} restore={restore} />
        </Section>
    );
}
