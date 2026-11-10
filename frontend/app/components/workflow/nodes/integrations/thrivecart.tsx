import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ThriveCartIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/thrivecart.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const ThriveCartNode: NodeDefinition = {
    type: 'automation-thrivecart', category: 'ecommerce', label: 'ThriveCart',
    description: 'Manage sales, subscriptions, refunds, affiliates and Learn students',
    Icon: ThriveCartIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ThriveCartIcon} iconColor="" />),
};
