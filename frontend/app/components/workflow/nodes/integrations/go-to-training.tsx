import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GoToTrainingIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/go-to-training.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const GoToTrainingNode: NodeDefinition = {
    type: 'automation-go-to-training', category: 'meetings', label: 'GoTo Training',
    description: 'Schedule trainings, register participants and retrieve session attendance and recordings',
    Icon: GoToTrainingIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GoToTrainingIcon} iconColor="" />),
};
