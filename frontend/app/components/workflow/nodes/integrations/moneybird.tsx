import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MoneybirdIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/moneybird.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const MoneybirdNode: NodeDefinition = {
    type: 'automation-moneybird', label: 'Moneybird',
    category: 'finance-accounting',
    description: 'Manage contacts, invoices, estimates, products and accounting settings',
    Icon: MoneybirdIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MoneybirdIcon} iconColor="" />),
};
