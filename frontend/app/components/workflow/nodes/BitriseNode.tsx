// Bitrise exposes current protected app, branch and build metadata reads.
// The original official white icon is contained on a dark background.
import { type ImgHTMLAttributes } from 'react';
import { type NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { type NodeDefinition } from './types';

export const BitriseIcon = ({ style, ...props }: ImgHTMLAttributes<HTMLImageElement>) => (
    <img {...props} src="/icons/bitrise.svg" alt="Bitrise"
        style={{ objectFit: 'contain', background: '#492f78', borderRadius: 8, padding: 8, ...style }} />
);
const BitriseNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={BitriseIcon} iconColor="" />;
export const BitriseNode: NodeDefinition = {
    type: 'automation-bitrise', category: 'developer-tools', label: 'Bitrise', description: 'Read protected apps, branches and build metadata',
    Icon: BitriseIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: BitriseNodeComponent,
};
