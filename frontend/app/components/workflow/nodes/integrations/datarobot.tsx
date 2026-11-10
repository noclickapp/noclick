import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const DataRobotIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/datarobot.svg" dark="/icons/datarobot-dark.svg" className={className} style={style} />
);

export const DataRobotNode: NodeDefinition = {
    type: 'automation-datarobot', category: 'ai', label: 'DataRobot',
    description: 'Manage DataRobot projects, models, datasets, deployments and use cases',
    Icon: DataRobotIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DataRobotIcon} iconColor="" />),
};
