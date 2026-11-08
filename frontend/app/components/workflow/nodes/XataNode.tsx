import { type ImgHTMLAttributes } from 'react';
import { type NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { type NodeDefinition } from './types';

export const XataIcon = ({ style, ...props }: ImgHTMLAttributes<HTMLImageElement>) => (
    <img {...props} src="/icons/xata.svg" alt="Xata" style={{ objectFit: 'contain', ...style }} />
);
const XataNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={XataIcon} iconColor="" />;
export const XataNode: NodeDefinition = {
    type: 'automation-xata', category: 'databases-storage', label: 'Xata', description: 'Read organization, project, branch and backup metadata',
    Icon: XataIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 }, component: XataNodeComponent,
};
