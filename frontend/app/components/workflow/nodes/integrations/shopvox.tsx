import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ShopvoxIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/shopvox.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const ShopvoxNode: NodeDefinition = {
    type: 'automation-shopvox', category: 'industry', label: 'shopVOX',
    description: 'Manage customers, contacts, quotes, sales orders, invoices, jobs and leads',
    Icon: ShopvoxIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ShopvoxIcon} iconColor="" />),
};
