import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const JoggAiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/jogg-ai.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const JoggAiNode: NodeDefinition = {
    type: 'automation-jogg-ai', category: 'ai', label: 'Jogg Ai',
    description: 'Generate avatar, product and template videos, write scripts and manage product information',
    Icon: JoggAiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={JoggAiIcon} iconColor="" />),
};
