import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const DreamstudioIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/dreamstudio.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const DreamstudioNode: NodeDefinition = {
    type: 'automation-dreamstudio', category: 'ai', label: 'DreamStudio',
    description: 'Generate, transform, upscale and inpaint images with Stability AI',
    keywords: ['Stability AI', 'Stable Diffusion', 'image generation'],
    Icon: DreamstudioIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DreamstudioIcon} iconColor="" />),
};
