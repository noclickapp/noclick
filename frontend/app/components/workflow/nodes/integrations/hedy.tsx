import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const HedyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/hedy.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const HedyNode: NodeDefinition = {
    type: 'automation-hedy', category: 'meetings', label: 'Hedy',
    description: 'Read meeting transcripts, highlights and to-dos; manage topics, contexts and vocabulary',
    keywords: ['meeting notes', 'transcripts', 'summaries', 'action items'],
    Icon: HedyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HedyIcon} iconColor="" />),
};
