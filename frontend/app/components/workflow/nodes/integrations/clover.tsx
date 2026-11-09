import { memo, type CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CloverIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/clover-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);
const CloverNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={CloverIcon} iconColor="" />
);

export const CloverNode: NodeDefinition = {
    type: 'automation-clover',
    label: 'Clover',
    description: 'Manage Clover orders, customers, payments and inventory, and watch for changes',
    category: 'ecommerce',
    Icon: CloverIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(CloverNodeComponent),
};
