// Skills, memories and machines on the account's Resources page: each item's body and header actions, and making one
// over its kind's list (a machine: rented, or a computer of yours). They're the same parts a space's Resources tab draws, read through the console's client
// (PlatformReads provides it as Work's).
import { AddMachine as AddMachineDialog, MachineChoices } from '../machine/AddMachine';
import { VettingNotice } from '../machine/VettingNotice';
import type { ResourceItem } from '@/screens/resources/model';
import { KnowledgeBody } from './knowledge/KnowledgePage';
import { KnowledgeHeadActions } from './knowledge/menus';
import { NewMemoryDialog, NewSkillDialog } from './knowledge/NewDialogs';
import { useKnowledge } from './knowledge/store';
import { MachineBody, usePlace } from './machines';

/** The kinds this module draws on the Resources page. */
export const WORK_KINDS = new Set(['skills', 'memories', 'machines']);

function MachineResourceBody({ item, now }: { item: ResourceItem; now: string }) {
    const place = usePlace(item.id);
    return place ? <MachineBody place={place} now={now} /> : null;
}

function KnowledgeResourceBody({ item, now }: { item: ResourceItem; now: string }) {
    const found = useKnowledge().find(item.id);
    return found ? <KnowledgeBody item={found} now={now} /> : null;
}

/** A skill's, memory's or machine's body on its Resources page. */
export function WorkResourceBody({ item, now }: { item: ResourceItem; now: string }) {
    return item.kind === 'machines' ? <MachineResourceBody item={item} now={now} /> : <KnowledgeResourceBody item={item} now={now} />;
}

/** A skill's or memory's header actions: attach it to agents, and its ⋯ (the page's own removal moves it to the trash). */
export function WorkResourceActions({ item }: { item: ResourceItem }) {
    const found = useKnowledge().find(item.id);
    if (!found || item.kind === 'machines') return null;
    return <KnowledgeHeadActions item={found} trash={false} />;
}

export function CreateSkill({ onDone }: { onDone: (id: string | null) => void }) {
    return <NewSkillDialog onClose={(made) => onDone(made?.id ?? null)} />;
}

export function CreateMemory({ onDone }: { onDone: (id: string | null) => void }) {
    return <NewMemoryDialog onClose={(made) => onDone(made?.id ?? null)} />;
}

/** Add machine: renting one from NoClick or adding a computer of yours (`way`, where one was picked already), each
 *  opening the machine here once it's made. */
export function AddMachine({ onDone, way }: { onDone: (id: string | null) => void; way?: string }) {
    return <AddMachineDialog onDone={onDone} way={way} />;
}

/** Above Machines' rows: NoClick's company check, while it waits or after it was declined. */
export function MachinesNotice() {
    return <VettingNotice />;
}

/** An empty Machines: both ways, each with its price, in place of a button; a pick opens Add machine on it. */
export function MachineWays({ onPick }: { onPick: (way: string) => void }) {
    return <MachineChoices onPick={onPick} />;
}
