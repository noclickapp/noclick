// Defines the Coinbase Exchange node for the canvas and integrations catalog.
// It uses the official publisher icon and finance category for discovery.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CoinbaseIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/coinbase.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const CoinbaseNode: NodeDefinition = {
    type: 'automation-coinbase', category: 'finance-accounting', label: 'Coinbase',
    description: 'Start workflows on new Coinbase Exchange orders, fills or account activity, and automate trading and market data',
    Icon: CoinbaseIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CoinbaseIcon} iconColor="" />),
};
