// What your own NoClick asked a space's NoClick about the space (`Workspace.questions`, read as you: your session in a
// space you joined), newest first, each with its answer once it comes. Read again on each `space_question` frame for
// the space (one asked, one answered), and when the space moves.
import { Workspace, type SpaceQuestion } from 'noclick';
import { cn } from '@/ui/utils';
import { useWorkV1 } from './agents/reads';
import { agoText } from './agents/states';
import { useWorkFrames } from '@/sdk/live';
import { CloseButton, PanelFrame } from './ui';
import { useSlot } from '@/slots';
import { REPLY_MARKDOWN } from './slots';

export const questionsKey = (workspaceId: string) => `work:space-questions:${workspaceId}`;

/** The questions your NoClick asked the space `workspaceId`'s NoClick, newest first; none for the personal space. */
export function useSpaceQuestions(workspaceId: string | null): SpaceQuestion[] | undefined {
    const read = useWorkV1(workspaceId ? questionsKey(workspaceId) : null, (client) => Workspace.questions(workspaceId!, { client }));
    const { refresh } = read;
    useWorkFrames('platform:resource', (frame) => {
        if (workspaceId && frame.kind === 'space_question' && frame.parent_id === workspaceId) void refresh();
    });
    useWorkFrames('platform:channel', (frame) => {
        if (workspaceId && frame.kind === 'workspace' && frame.workspace_id === workspaceId) void refresh();
    });
    return read.data;
}

export const ASKED_TITLE = 'Asked by your NoClick';

/** The questions beside the space's NoClick channel: each with its answer, or that it waits for one. */
export function SpaceQuestionsPanel({ questions, spaceName, phone, onClose }: { questions: readonly SpaceQuestion[]; spaceName: string; phone?: boolean; onClose: () => void }) {
    const MarkdownRenderer = useSlot(REPLY_MARKDOWN);
    return (
        <PanelFrame phone={phone}>
            {/* On a phone the bar above names it and carries the way back. */}
            {!phone && (
                <div className="flex items-center gap-2 px-5 pb-3 pt-4">
                    <p className="text-[16px] font-semibold">{ASKED_TITLE}</p>
                    <p className="truncate text-[13px] text-muted-foreground">{spaceName}</p>
                    <CloseButton onClose={onClose} />
                </div>
            )}
            <ol className="min-h-0 flex-1 overflow-y-auto px-5 pb-5 scrollbar-subtle" data-testid="space-questions">
                {questions.map((q) => (
                    <li key={q.id} className="border-b border-border py-4 last:border-0 dark:border-foreground/[0.08]">
                        <p className="text-[14px] font-medium leading-snug text-foreground">{q.question}</p>
                        {q.askedAt && <p className="mt-0.5 text-[12px] text-muted-foreground">Asked {agoText(Date.now() - q.askedAt.getTime())}</p>}
                        <div className={cn('mt-2.5 text-[14px] leading-relaxed', q.status === 'answered' ? 'text-foreground' : 'text-muted-foreground')}>
                            {q.status === 'answered' && q.answer ? <MarkdownRenderer content={q.answer} /> : q.status === 'unanswered' ? 'No answer came.' : 'Waiting for an answer'}
                        </div>
                    </li>
                ))}
            </ol>
        </PanelFrame>
    );
}
