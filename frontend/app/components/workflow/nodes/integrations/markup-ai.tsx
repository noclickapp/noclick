import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MarkupAiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/markup-ai.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const MarkupAiNode: NodeDefinition = {
    type: 'automation-markup-ai', category: 'ai', label: 'Markup AI',
    description: 'Check content, run agents, and manage brand terminology',
    Icon: MarkupAiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MarkupAiIcon} iconColor="" />),
};
