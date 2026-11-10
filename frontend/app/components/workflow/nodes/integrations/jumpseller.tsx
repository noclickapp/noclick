import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const JumpsellerIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/jumpseller.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const JumpsellerNode: NodeDefinition = {
    type: 'automation-jumpseller', category: 'ecommerce', label: 'Jumpseller',
    description: 'Manage products, orders, customers, categories and inventory',
    Icon: JumpsellerIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={JumpsellerIcon} iconColor="" />),
};
