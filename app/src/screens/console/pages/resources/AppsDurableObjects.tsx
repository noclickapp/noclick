// An app's Durable Objects on its page, after its bindings: the same list as the app's page in Resources
// (screens/resources/AppDurableObjects), read with the console's own client, its deletion previewed through
// previewDelete as Resources previews it. An app that declares none shows nothing.
import { useMemo } from 'react';
import { previewDelete, TrashItem, type Project } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import { DurableObjectsList, useDurableObjects } from '@/screens/resources/AppDurableObjects';
import { costText, type DeletePreview, type TrashRestore } from '@/screens/resources/durableObjects';
import { impactOf } from '@/screens/resources/platform';
import { useConsole } from '../../hooks/useConsole';
import { PageSection } from '../../ui/PageHeader';

export function AppDurableObjectsSection({ project }: { project: Project }) {
    const { client } = useConsole();
    const read = useDurableObjects(project);
    const preview = useMemo<DeletePreview>(
        () => async (path, user) => impactOf((await previewDelete('DELETE', path, { client, user })).impact),
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
        <PageSection
            title="Durable Objects"
            right={cost && <span className="text-[13px] tabular-nums text-muted-foreground">{cost}</span>}
            note="Each class its code declares, in each environment. Their data survives releases; deleting a class moves it to the trash for 30 days."
        >
            <DurableObjectsList project={project} read={read} preview={preview} restore={restore} />
        </PageSection>
    );
}
