import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const FlutterwaveIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/flutterwave.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const FlutterwaveNode: NodeDefinition = {
    type: 'automation-flutterwave', label: 'Flutterwave',
    category: 'finance-accounting',
    description: 'Start workflows from payment events and manage customers, charges, transfers, refunds and balances',
    Icon: FlutterwaveIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FlutterwaveIcon} iconColor="" />),
};
