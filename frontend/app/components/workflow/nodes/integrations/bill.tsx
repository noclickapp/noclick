import { memo, type CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const BillIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/bill-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const BillNode: NodeDefinition = {
    type: 'automation-bill',
    label: 'BILL',
    description: 'Manage vendors, bills, approvals, payments, and customers; trigger workflows from BILL events',
    category: 'finance-accounting',
    keywords: ['bill.com', 'accounts payable', 'accounts receivable', 'vendor payments'],
    Icon: BillIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BillIcon} iconColor="" />),
};
