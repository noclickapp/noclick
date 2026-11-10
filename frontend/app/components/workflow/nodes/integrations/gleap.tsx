import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GleapIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/gleap.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const GleapNode: NodeDefinition = {
    type: 'automation-gleap', label: 'Gleap',
    category: 'support',
    description: 'Automate contacts, conversations, messages, workflows and webhooks',
    Icon: GleapIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GleapIcon} iconColor="" />),
};
