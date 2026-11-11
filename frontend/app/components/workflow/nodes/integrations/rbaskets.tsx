import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RBasketsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/rbaskets.svg" alt="" aria-hidden="true" className={className} style={style} />
);

export const RBasketsNode: NodeDefinition = {
    type: 'automation-rbaskets', category: 'developer-tools', label: 'Request Baskets API',
    description: 'Inspect captured HTTP requests, manage baskets, forwarding and custom responses',
    keywords: ['request baskets', 'rbaskets', 'request bin', 'HTTP', 'API testing'],
    Icon: RBasketsIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RBasketsIcon} iconColor="" />),
};
