import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const HitpayIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <>
        <img
            src="/icons/hitpay.svg"
            alt=""
            aria-hidden="true"
            className={`${className ?? ''} dark:hidden`}
            style={
                {
                    ...style,
                    '--brand-invert': 0,
                    objectFit: 'contain',
                } as CSSProperties
            }
        />
        <img
            src="/icons/hitpay-dark.svg"
            alt=""
            aria-hidden="true"
            className={`${className ?? ''} hidden dark:block`}
            style={
                {
                    ...style,
                    '--brand-invert': 0,
                    objectFit: 'contain',
                } as CSSProperties
            }
        />
    </>
);

export const HitpayNode: NodeDefinition = {
    type: 'automation-hitpay',
    category: 'finance-accounting',
    label: 'HitPay',
    description:
        'Manage payment links, customers and refunds; read charges, balances, payouts and subscription plans',
    keywords: ['hitpay', 'hit-pay', 'payments', 'refunds'],
    Icon: HitpayIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={HitpayIcon} iconColor="" />
    )),
};
