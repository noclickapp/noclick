import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const DeepimageIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/deepimage.svg" dark="/icons/deepimage-dark.svg" className={className} style={style} />
);

export const DeepimageNode: NodeDefinition = {
    type: 'automation-deepimage', category: 'ai', label: 'Deepimage',
    description: 'Upscale and enhance images, remove backgrounds, generate images and track processing jobs',
    keywords: ['deep-image', 'image processing', 'upscale', 'background removal'],
    Icon: DeepimageIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DeepimageIcon} iconColor="" />),
};
