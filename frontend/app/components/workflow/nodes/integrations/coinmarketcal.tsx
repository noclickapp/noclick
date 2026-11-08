/** CoinMarketCal catalog and canvas definition for the self-registering v2 integration.
 * Makes the crypto-event reads discoverable with the official publisher icon. */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CoinMarketCalIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/coinmarketcal.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const CoinMarketCalNode: NodeDefinition = {
    type: 'automation-coinmarketcal', category: 'finance-accounting', label: 'CoinMarketCal',
    description: 'Read crypto events, coins, cancellations, exports and API usage',
    Icon: CoinMarketCalIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CoinMarketCalIcon} iconColor="" />),
};
