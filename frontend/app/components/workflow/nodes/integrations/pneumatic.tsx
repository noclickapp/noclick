import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const PneumaticIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/pneumatic.svg" dark="/icons/pneumatic-dark.svg" className={className} style={style} />
);

export const PneumaticNode: NodeDefinition = {
    type: 'automation-pneumatic', category: 'productivity', label: 'Pneumatic',
    description: 'Run workflows, manage tasks and read templates and accounts',
    Icon: PneumaticIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PneumaticIcon} iconColor="" />),
};
