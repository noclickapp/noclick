import { memo, type CSSProperties } from 'react';
import { type NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { type NodeDefinition } from '~/components/workflow/nodes/types';

const BrightcoveIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/brightcove.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
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
