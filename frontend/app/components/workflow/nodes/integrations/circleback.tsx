import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CirclebackIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/circleback.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const CirclebackNode: NodeDefinition = {
    type: 'automation-circleback', category: 'meetings', label: 'Circleback',
    description: 'Manage meeting notes, transcripts, action items, tags and contacts',
    keywords: ['meeting assistant', 'meeting notes', 'transcription'],
    Icon: CirclebackIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CirclebackIcon} iconColor="" />),
};
