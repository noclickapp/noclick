import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const MarketstackIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/marketstack.svg" dark="/icons/marketstack-dark.svg" className={className} style={{ ...style, objectFit: 'contain' }} />
);

export const MarketstackNode: NodeDefinition = {
    type: 'automation-marketstack', category: 'finance-accounting', label: 'Marketstack',
    description: 'Read stock prices, intraday history, splits, dividends, tickers and exchanges',
    Icon: MarketstackIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MarketstackIcon} iconColor="" />),
};
