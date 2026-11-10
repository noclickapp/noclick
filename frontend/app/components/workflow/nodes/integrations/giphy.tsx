import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GiphyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/giphy.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const GiphyNode: NodeDefinition = {
    type: 'automation-giphy', category: 'media', label: 'GIPHY',
    description: 'Search, find trending content and retrieve GIFs and stickers',
    Icon: GiphyIcon, keywords: ['gif', 'gifs', 'stickers', 'giphy'], iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GiphyIcon} iconColor="" />),
};
