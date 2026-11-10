import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PolymarketIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/polymarket.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' }}
    />
);

export const PolymarketNode: NodeDefinition = {
    type: 'automation-polymarket',
    category: 'finance-accounting',
    label: 'Polymarket',
    description:
        'Read market prices, manage orders and trigger workflows or agents on new trades',
    Icon: PolymarketIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={PolymarketIcon} iconColor="" />
    )),
};
