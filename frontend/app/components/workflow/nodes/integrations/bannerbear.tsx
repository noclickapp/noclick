import { memo, type CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
// Unmodified official Bannerbear brand icon from the provider website.
const BannerbearIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/bannerbear.svg" dark="/icons/bannerbear-dark.svg" className={className} style={style} />
);

export const BannerbearNode: NodeDefinition = {
    type: 'automation-bannerbear',
    label: 'Bannerbear',
    description: 'Render personalized images, animations, and campaign batches',
    category: 'media',
    keywords: ['marketing', 'image', 'animation', 'template', 'batch', 'campaign'],
    Icon: BannerbearIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BannerbearIcon} iconColor="" />),
};
