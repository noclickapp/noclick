import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MinimaxIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/minimax.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const MinimaxNode: NodeDefinition = {
    type: 'automation-minimax', category: 'ai', label: 'MiniMax',
    description: 'Generate text, images, music, speech and videos; manage voices, files and tasks',
    keywords: ['minimax', 'hailuo', 'text to speech', 'video generation', 'voice cloning'],
    Icon: MinimaxIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MinimaxIcon} iconColor="" />),
};
