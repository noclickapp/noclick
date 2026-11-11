import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const VideoUpscalerIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/videoupscaler.svg" alt="" aria-hidden="true" className={className} style={style} />
);

export const VideoUpscalerNode: NodeDefinition = {
    type: 'automation-videoupscaler', category: 'media', label: 'VideoUpscaler',
    description: 'Upscale and enhance videos, create upload URLs, monitor tasks and check credits',
    keywords: ['video', 'upscale', '4k', 'enhance', 'denoise', 'interpolation'],
    Icon: VideoUpscalerIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={VideoUpscalerIcon} iconColor="" />),
};
