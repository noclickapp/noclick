import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PaymentsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/payments.svg" alt="" aria-hidden="true" className={className} style={style} />
);

export const PaymentsNode: NodeDefinition = {
    type: 'automation-payments', category: 'finance-accounting', label: 'GOV.UK Pay',
    description: 'Create and track payments, issue refunds, manage recurring payment agreements and watch for new payments.',
    Icon: PaymentsIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PaymentsIcon} iconColor="" />),
};
