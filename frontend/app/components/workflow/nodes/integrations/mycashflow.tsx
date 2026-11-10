import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MyCashflowIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/mycashflow.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const MyCashflowNode: NodeDefinition = {
    type: 'automation-mycashflow', category: 'ecommerce', label: 'MyCashflow',
    description: 'Automate customers, products, orders, inventory and signed order events',
    Icon: MyCashflowIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MyCashflowIcon} iconColor="" />),
};
