import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MinerstatIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/minerstat.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const MinerstatNode: NodeDefinition = {
    type: 'automation-minerstat', category: 'industry', label: 'Minerstat',
    description: 'Mining coins, hardware, algorithms, pools and profitability',
    keywords: ['mining', 'crypto', 'hashrate', 'profitability'],
    Icon: MinerstatIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MinerstatIcon} iconColor="" />),
};
