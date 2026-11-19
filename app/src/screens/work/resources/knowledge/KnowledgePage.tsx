// A skill's or memory's own page: its head (what it is, where it came from, who may have it, its actions) over its
// sections. A space's Resources tab draws it whole; the account's Resources draws the sections inside its own page
// (KnowledgeBody) and the actions in its header (KnowledgeActions).
import type { ReactNode } from 'react';
import { Laptop } from 'lucide-react';
import type { Knowledge, Skill } from '@/screens/resources/knowledge';
import { Skeleton } from '@/ui/skeleton';
import { AgentFace, Chip, ItemMark } from './parts';
import { MemoryBody } from './MemoryBody';
import { KnowledgeHeadActions } from './menus';
import { SkillBody, useSkillVersions } from './SkillBody';
import { titleOf, useKnowledge } from './store';

/** Where it came from: a person, your code, an agent (its own memory, a skill it started), or your laptop. */
function SourceChip({ item }: { item: Knowledge }) {
    const k = useKnowledge();
    if (item.kind === 'memory') {
        const owner = item.agentId ? k.agent(item.agentId) : undefined;
        return owner ? (
            <Chip>
                <AgentFace agent={owner} size={16} />
                Learned by {owner.name}
            </Chip>
        ) : (
            <Chip>Yours</Chip>
        );
    }
    return <SkillSource skill={item} />;
}

function SkillSource({ skill }: { skill: Skill }) {
    const versions = useSkillVersions(skill).data;
    const first = versions?.[versions.length - 1]?.createdBy;
    if (first?.type === 'agent' && first.agentId)
        return (
            <Chip>
                <AgentFace agent={{ id: first.agentId, name: first.agentName ?? '' }} size={16} />
                Started by {first.agentName}
            </Chip>
        );
    if (first?.type === 'api')
        return (
            <Chip>
                <Laptop className="h-3 w-3" strokeWidth={2} />
                Brought in by your code
            </Chip>
        );
    return <Chip>Yours</Chip>;
}

/** Its head: mark, name, the line agents see, where it came from and who may have it, then its actions. */
export function KnowledgeHead({ item, actions }: { item: Knowledge; actions: ReactNode }) {
    const k = useKnowledge();
    const owner = item.kind === 'memory' && item.agentId ? k.agent(item.agentId) : undefined;
    return (
        <header className="px-5 pt-6 sm:px-8" data-testid="knowledge-head">
            <div className="flex flex-wrap items-start gap-4">
                <ItemMark kind={item.kind} className="h-11 w-11" iconClassName="h-5 w-5" />
                <div className="min-w-0 flex-1">
                    <h2 className="truncate text-[22px] font-semibold leading-tight tracking-[-0.01em]">{titleOf(item, owner)}</h2>
                    <p className="mt-1 text-sm leading-snug text-muted-foreground">{item.description}</p>
                    <div className="mt-3 flex flex-wrap gap-1.5">
                        <SourceChip item={item} />
                        <Chip>{owner ? `Only ${owner.name} writes it` : item.userId ? 'One of your users’' : 'Whole account'}</Chip>
                        {item.kind === 'skill' ? <Chip>v{item.version}</Chip> : item.entryCount !== null ? <Chip>{item.entryCount} entries</Chip> : null}
                        {item.kind === 'skill' && item.always && <Chip>In every turn</Chip>}
                    </div>
                </div>
                <div className="flex w-full items-center gap-2 sm:w-auto">{actions}</div>
            </div>
        </header>
    );
}

/** Its sections, under whatever head the page draws. */
export function KnowledgeBody({ item, now, from, onOpen }: { item: Knowledge; now: string; from?: string; onOpen?: (id: string) => void }) {
    return item.kind === 'skill' ? <SkillBody key={item.id} skill={item} from={from} onOpen={onOpen} now={now} /> : <MemoryBody key={item.id} memory={item} now={now} />;
}


/** The whole page, by id: a deleted one says so. */
export function KnowledgePage({ id, now, from, onOpen, onTrashed, actions }: { id: string; now: string; from?: string; onOpen?: (id: string) => void; onTrashed?: () => void; actions?: ReactNode }) {
    const k = useKnowledge();
    const item = k.find(id);
    if (!item) {
        if (k.loading)
            return (
                <div className="space-y-3 px-5 pt-6 sm:px-8">
                    <Skeleton className="h-11 w-11 rounded-full" />
                    <Skeleton className="h-5 w-1/3" />
                </div>
            );
        return <p className="px-5 py-8 text-sm text-muted-foreground sm:px-8">It’s gone: it was deleted.</p>;
    }
    return (
        <div className="pb-12" data-testid="knowledge-page">
            <KnowledgeHead
                item={item}
                actions={
                    <>
                        {actions}
                        <KnowledgeHeadActions item={item} onTrashed={onTrashed} />
                    </>
                }
            />
            <div className="px-5 sm:px-8">
                <KnowledgeBody item={item} now={now} from={from} onOpen={onOpen} />
            </div>
        </div>
    );
}
