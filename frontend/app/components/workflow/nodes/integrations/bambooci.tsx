import { type ImgHTMLAttributes } from 'react';
import { type NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { type NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
export const BambooCIIcon = ({ className, style, ...props }: ImgHTMLAttributes<HTMLImageElement>) => (
    <ThemedBrandImg light="/icons/bambooci.svg" dark="/icons/bambooci-dark.svg" className={className} style={style} {...props} />
);
const BambooCINodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={BambooCIIcon} iconColor="" />;
export const BambooCINode: NodeDefinition = {
    type: 'automation-bambooci', category: 'developer-tools', label: 'Bamboo CI', description: 'Read bound Bamboo project and plan metadata',
    Icon: BambooCIIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 }, component: BambooCINodeComponent,
};
