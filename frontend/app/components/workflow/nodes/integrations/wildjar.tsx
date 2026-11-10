import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WildJarIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/wildjar.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const WildJarNode: NodeDefinition = {
    type: 'automation-wildjar', category: 'communication', label: 'WildJar',
    description: 'Read outbound call details and tracking numbers, manage routing and send SMS',
    keywords: ['call tracking', 'SMS', 'routing', 'DNI'],
    Icon: WildJarIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WildJarIcon} iconColor="" />),
};
