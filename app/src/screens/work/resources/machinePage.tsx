// A machine's own page under Resources → Machines, where a row opens: a NoClick machine or a computer of yours drawn as
// the agent page's sibling (its lead, name, kind and three figures), then its sections; a sandbox up now keeps the
// shared anatomy (its name, facts and who's on it). Drawn inside PlatformReads, which provides Work's client.
import type { ResourceItem } from '@/screens/resources/model';
import { ResourcePageFrame } from '@/screens/resources/ResourceDetail';
import { PAGE_TITLE } from '@/ui/titles';
import { cn } from '@/ui/utils';
import { MachineDetail } from '../machine/MachineDetail';
import { isOwn, MachineBody, OwnNotes, placeKind, usePlace } from './machines';

export function MachineResourcePage({
    item,
    now,
    onBack,
}: {
    item: ResourceItem;
    now: string;
    onBack: (to: 'all' | 'kind') => void;
}) {
    const place = usePlace(item.id);
    const machine = !!place && (isOwn(place) || place.kind === 'machine');
    return (
        <ResourcePageFrame kindLabel="Machines" onBack={onBack}>
            {machine ? (
                <MachineDetail
                    id={item.id}
                    now={Date.parse(now)}
                    own={isOwn(place) ? place : null}
                    onDeleted={() => onBack('kind')}
                    between={<OwnNotes place={place} />}
                />
            ) : (
                <>
                    <header>
                        <h1
                            className={cn(
                                'min-w-0 break-words sm:truncate',
                                PAGE_TITLE
                            )}
                        >
                            {item.title}
                        </h1>
                        <p className="mt-1 text-[14px] leading-snug text-muted-foreground">
                            {place ? placeKind(place) : item.subtitle}
                        </p>
                    </header>
                    {place ? (
                        <MachineBody place={place} now={now} />
                    ) : (
                        <p className="mt-6 text-[14px] text-muted-foreground">
                            It isn’t up now.
                        </p>
                    )}
                </>
            )}
        </ResourcePageFrame>
    );
}
