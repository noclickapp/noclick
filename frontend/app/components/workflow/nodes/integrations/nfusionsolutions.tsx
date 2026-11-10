import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const NFusionIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/nfusionsolutions.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={style}
    />
);

export const NFusionSolutionsNode: NodeDefinition = {
    type: 'automation-nfusionsolutions',
    category: 'finance-accounting',
    label: 'nFusion Solutions Market Data API',
    description:
        'Read precious metal prices and currency rates, monitor historical intervals, and manage price adjustments.',
    keywords: [
        'gold',
        'silver',
        'platinum',
        'palladium',
        'forex',
        'exchange rates',
        'market data',
        'bullion',
    ],
    Icon: NFusionIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={NFusionIcon} iconColor="" />
    )),
};
