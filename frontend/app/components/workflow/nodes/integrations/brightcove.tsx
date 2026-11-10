import { memo, type CSSProperties } from 'react';
import { type NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { type NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const BrightcoveIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/brightcove.svg" dark="/icons/brightcove-dark.svg" className={className} style={style} />
);

const BrightcoveNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={BrightcoveIcon} iconColor="#2563EB" />
);

export const BrightcoveNode: NodeDefinition = {
    type: 'automation-brightcove',
    label: 'Brightcove',
    description: 'Manage Video Cloud video, playlist, folder and label metadata',
    category: 'media',
    Icon: BrightcoveIcon,
    iconColor: '#2563EB',
    dimensions: { width: 90, height: 90, iconSize: 60 },
    component: memo(BrightcoveNodeComponent),
};
