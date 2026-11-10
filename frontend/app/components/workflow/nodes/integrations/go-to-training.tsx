import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const GoToTrainingIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/go-to-training.svg" dark="/icons/go-to-training-dark.svg" className={className} style={style} />
);

export const GoToTrainingNode: NodeDefinition = {
    type: 'automation-go-to-training', category: 'meetings', label: 'GoTo Training',
    description: 'Schedule trainings, register participants and retrieve session attendance and recordings',
    Icon: GoToTrainingIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GoToTrainingIcon} iconColor="" />),
};
