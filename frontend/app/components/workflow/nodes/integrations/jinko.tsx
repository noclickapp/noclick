import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const JinkoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/jinko.svg" dark="/icons/jinko-dark.svg" className={className} style={style} />
);

export const JinkoNode: NodeDefinition = {
    type: 'automation-jinko', category: 'bookings', label: 'Jinko',
    description: 'Search travel, manage trips, check out and service bookings',
    Icon: JinkoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={JinkoIcon} iconColor="" />),
};
