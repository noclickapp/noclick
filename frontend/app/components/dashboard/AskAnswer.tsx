// Answers a parked builder question from the Dashboard with the builder's own
// wizard (BuilderInputDrawer): credential inputs render the real credential
// picker, choices render as options, config fields load their dynamic options,
// and Skip/Dismiss resumes the builder without an answer — exactly what the
// builder chat offers, so the two can never drift.
import { BuilderInputDrawer } from '~/components/chat/drawer/BuilderInputDrawer';
import type { InputRequest } from '~/components/workflow/workflowGeneratorMock';
import { useDashboardActions } from '~/components/dashboard/primitives';
import type { AttentionItem } from '~/components/dashboard/types';

export function AskAnswer({ item }: { item: AttentionItem }) {
    const actions = useDashboardActions();
    const inputs = (item.inputs ?? []) as InputRequest[];
    if (!inputs.length) return null;
    return (
        <div data-testid="dashboard-ask-answer">
            <BuilderInputDrawer
                embedded
                inputs={inputs}
                title={item.title}
                onSubmit={(values) => actions.answerAsk(item, values)}
                onDismiss={actions.dismissAsk ? () => actions.dismissAsk?.(item) : undefined}
                onShare={actions.shareAsk ? () => actions.shareAsk!(item) : undefined}
            />
        </div>
    );
}
