import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AlpacaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/alpaca.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const AlpacaNode: NodeDefinition = {
    type: 'automation-alpaca', label: 'Alpaca',
    category: 'finance-accounting',
    description: 'Manage trading accounts, orders, positions, assets and watchlists',
    Icon: AlpacaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AlpacaIcon} iconColor="" />),
};
