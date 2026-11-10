import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const NinetyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/ninety.svg" dark="/icons/ninety-dark.svg" className={className} style={style} />
);

export const NinetyNode: NodeDefinition = {
    type: 'automation-ninety', category: 'productivity', label: 'Ninety',
    description: 'Manage To-Dos, Issues, Rocks, Milestones, Measurables and Headlines',
    Icon: NinetyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={NinetyIcon} iconColor="" />),
};
