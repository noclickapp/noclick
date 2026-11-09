import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RecallaiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/recallai.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const RecallaiNode: NodeDefinition = {
    type: 'automation-recallai', category: 'meetings', label: 'Recall.ai',
    keywords: ['Recallai', 'meeting recording', 'meeting bot', 'transcription'],
    description: 'Manage meeting bots, recordings, transcript artifacts and linked calendars',
    Icon: RecallaiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RecallaiIcon} iconColor="" />),
};
