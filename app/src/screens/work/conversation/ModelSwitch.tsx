// A move between model connections in an agent's chat: the one quiet
// line each leaves, on the reader's clock. Moved to another connection, and who said so (the owner's words open in the
// channel where they wrote them); waiting for a plan's reset; back on the one it left. A move to another harness says
// what changes under it. A turn its plan's limit stopped says so in the same line where no move's line says it.
import { useContext, type ReactNode } from 'react';
import { ArrowLeftRight, Hourglass, Undo2, type LucideIcon } from 'lucide-react';
import type { ModelSwitchNote } from '@/lib/agentThread/thread';
import type { HarnessInfo } from 'noclick';
import { cn } from '@/ui/utils';
import { modelName, useHarnesses, useHarnessModels, useModelAccounts } from '../newAgent/catalog';
import { switchWords, type Told } from '../newAgent/switchWords';
import { WorkNavContext } from '../nav';
import { channelHref, openChannelInWork } from '../place';

const ICON = { switched: ArrowLeftRight, waiting: Hourglass, back_on: Undo2 } as const;
const INLINE_LINK = 'rounded-sm underline decoration-foreground/30 underline-offset-[3px] transition-colors hover:text-foreground hover:decoration-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

/** One quiet line in the chat: its mark, what happened in bold, then the rest. */
export function QuietLine({ icon: Icon, children, className, ...data }: { icon: LucideIcon; children: ReactNode; className?: string } & Record<`data-${string}`, string>) {
    return (
        <div {...data} className={cn('px-1 py-1.5', className)}>
            <div className="flex items-start gap-2 rounded-2xl px-3 py-2 text-[12.5px] leading-[1.45] text-muted-foreground ring-1 ring-inset ring-border dark:ring-foreground/[0.08]">
                <Icon aria-hidden className="mt-[2px] h-3.5 w-3.5 shrink-0" strokeWidth={2} />
                <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">{children}</span>
            </div>
        </div>
    );
}

/** A turn its plan's limit stopped, where no move's line says so: the platform's own words for it. */
export function PlanLimitLine({ message, className }: { message: string; className?: string }) {
    return (
        <QuietLine icon={Hourglass} className={className} data-row="plan-limit">
            <span className="font-medium text-foreground">{message}</span>
        </QuietLine>
    );
}

/** Who said so, opening the channel they wrote it in: Work's own way where it's open, else Work on that channel. */
function ToldBy({ told }: { told: Told }) {
    const nav = useContext(WorkNavContext);
    const channel = told.channel;
    if (!channel) return <>{told.text}</>;
    return (
        <a
            href={channelHref(channel)}
            className={INLINE_LINK}
            onClick={(e) => {
                if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
                e.preventDefault();
                if (nav) nav.openChannel(channel);
                else openChannelInWork(channel);
            }}
        >
            {told.text}
        </a>
    );
}

/** A model as its harness's list names it ("Opus 5.5"), for the harnesses a move went between. */
function useModelNames(names: readonly (string | null)[]): (harness: string, id: string) => string {
    const harnesses = useHarnesses();
    const find = (name: string | null): HarnessInfo | undefined => (name ? harnesses.data?.find((h) => h.name === name) : undefined);
    const fromModels = useHarnessModels(find(names[0]));
    const toModels = useHarnessModels(find(names[1]));
    return (harness, id) => modelName((harness === names[0] ? fromModels : toModels).data?.find((m) => m.id === id)?.label, id);
}

/** One move, as its line in the chat. */
export function ModelSwitchLine({ note, agentName }: { note: ModelSwitchNote; agentName: string }) {
    const { accounts } = useModelAccounts();
    const model = useModelNames([note.harnessFrom, note.harnessTo]);
    const { lead, told, detail } = switchWords(note, { accounts, agentName, model });
    return (
        <QuietLine icon={ICON[note.state]} data-row="model-switch" data-state={note.state}>
            <span className="font-medium text-foreground">{lead}</span>
            {told && (
                <>
                    {' · '}
                    <ToldBy told={told} />
                </>
            )}
            {note.state === 'waiting' && detail && <> · {detail}</>}
            {note.state !== 'waiting' && detail && <span className="block pt-0.5">{detail}</span>}
        </QuietLine>
    );
}
