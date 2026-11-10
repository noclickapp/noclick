import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MemelordIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/memelord.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const MemelordNode: NodeDefinition = {
    type: 'automation-memelord', category: 'media', label: 'Memelord',
    description: 'Search templates, generate and edit image and video memes, and run AI media tools',
    keywords: ['meme', 'caption', 'jester', 'image', 'video'],
    Icon: MemelordIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MemelordIcon} iconColor="" />),
};
