import { type ImgHTMLAttributes } from 'react';
import { type NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { type NodeDefinition } from './types';

export const AdaptyIcon = ({ style, ...props }: ImgHTMLAttributes<HTMLImageElement>) => (
    <img {...props} src="/icons/adapty.svg" alt="Adapty" style={{ objectFit: 'contain', ...style }} />
);
const AdaptyNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={AdaptyIcon} iconColor="" />;
export const AdaptyNode: NodeDefinition = {
    type: 'automation-adapty',
    label: 'Adapty',
    description: 'Manage app profiles and read or change profile access levels',
    Icon: AdaptyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 60 },
    component: AdaptyNodeComponent,
};
