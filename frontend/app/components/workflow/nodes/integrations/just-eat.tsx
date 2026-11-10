// Display Just Eat UK delivery operations in the workflow and integration catalogs.
// The icon comes from Just Eat's official API documentation, pinned by its sidecar.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const JustEatIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/just-eat.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const JustEatNode: NodeDefinition = {
    type: 'automation-just-eat', category: 'ecommerce', label: 'Just Eat UK',
    description: 'Estimate, create and track partner deliveries, manage collection points and receive delivery events',
    keywords: ['JustEat', 'JET', 'delivery', 'courier', 'food', 'takeaway'],
    Icon: JustEatIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={JustEatIcon} iconColor="" />),
};
