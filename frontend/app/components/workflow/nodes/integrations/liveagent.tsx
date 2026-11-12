import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LiveAgentIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/liveagent.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const LiveAgentNode: NodeDefinition = {
    type: 'automation-liveagent', category: 'support', label: 'LiveAgent',
    description: 'Monitor agent activity and availability, read ticket fields and manage departments',
    Icon: LiveAgentIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LiveAgentIcon} iconColor="" />),
};
