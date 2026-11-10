import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const HyrosIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/hyros.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const HyrosNode: NodeDefinition = {
    type: 'automation-hyros', category: 'marketing', label: 'Hyros',
    description: 'Sync leads, sales, orders, calls, products, sources and subscriptions',
    Icon: HyrosIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HyrosIcon} iconColor="" />),
};
