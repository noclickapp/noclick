import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const RoamIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/roam.svg" dark="/icons/roam-dark.svg" className={className} style={style} />
);

export const RoamNode: NodeDefinition = {
    type: 'automation-roam', category: 'communication', label: 'Roam',
    description: 'Automate Roam chat, users, groups and meetings',
    Icon: RoamIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RoamIcon} iconColor="" />),
};
