import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CoinGeckoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/coingecko.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const CoinGeckoNode: NodeDefinition = {
    type: 'automation-coingecko', label: 'CoinGecko',
    category: 'finance-accounting',
    description: 'Read cryptocurrency prices, market charts, exchanges and global data',
    Icon: CoinGeckoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CoinGeckoIcon} iconColor="" />),
};
