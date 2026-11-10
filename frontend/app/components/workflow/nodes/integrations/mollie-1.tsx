import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MollieIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/mollie-1.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' }} />
        <img src="/icons/mollie-1-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' }} />
    </>
);

export const MollieNode: NodeDefinition = {
    type: 'automation-mollie-1', category: 'finance-accounting', label: 'Mollie',
    description: 'Automate Mollie payments and react to payment, refund, chargeback and payment-link events',
    Icon: MollieIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MollieIcon} iconColor="" />),
};
