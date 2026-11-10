import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const BtcpayServerIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/btcpay-server.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const BtcpayServerNode: NodeDefinition = {
    type: 'automation-btcpay-server', label: 'BTCPay Server',
    category: 'finance-accounting',
    description: 'Automate invoices, payment requests, pull payments and store reads',
    Icon: BtcpayServerIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BtcpayServerIcon} iconColor="" />),
};
