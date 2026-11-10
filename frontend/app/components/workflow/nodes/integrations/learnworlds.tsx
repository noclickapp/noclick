import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const LearnWorldsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/learnworlds.svg" dark="/icons/learnworlds-dark.svg" className={className} style={style} />
);

export const LearnWorldsNode: NodeDefinition = {
    type: 'automation-learnworlds', category: 'courses', label: 'LearnWorlds',
    description: 'Manage learners, courses, enrollments, progress and payments',
    Icon: LearnWorldsIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LearnWorldsIcon} iconColor="" />),
};
